import cmp.visitor as visitor
from cmp.semantic import Scope, SemanticError, ErrorType, IntType, BoolType, SelfType, AutoType, LCA
from cmp.ast import ProgramNode, ClassDeclarationNode, AttrDeclarationNode, FuncDeclarationNode
from cmp.ast import AssignNode, CallNode, CaseNode, BlockNode, LoopNode, ConditionalNode, LetNode
from cmp.ast import ArithmeticNode, ComparisonNode, EqualNode
from cmp.ast import VoidNode, NotNode, NegNode
from cmp.ast import ConstantNumNode, ConstantStringNode, ConstantBoolNode, VariableNode, InstantiateNode


WRONG_SIGNATURE = 'Method "%s" already defined in "%s" with a different signature.'
SELF_IS_READONLY = 'Variable "self" is read-only.'
LOCAL_ALREADY_DEFINED = 'Variable "%s" is already defined in method "%s".'
INCOMPATIBLE_TYPES = 'Cannot convert "%s" into "%s".'
VARIABLE_NOT_DEFINED = 'Variable "%s" is not defined in "%s".'
INVALID_OPERATION = 'Operation is not defined between "%s" and "%s".'
INVALID_TYPE = 'SELF_TYPE is not valid'

class TypeChecker:
    def __init__(self, context, manager, errors=[]):
        self.context = context
        self.current_type = None
        self.current_method = None
        self.errors = errors
        self.manager = manager

        # built-in types
        self.obj_type = self.context.get_type('Object')
        self.int_type = self.context.get_type('Int')
        self.bool_type = self.context.get_type('Bool')
        self.string_type = self.context.get_type('String')

    @visitor.on('node')
    def visit(self, node, scope=None):
        pass

    @visitor.when(ProgramNode)
    def visit(self, node, scope=None):
        scope = Scope()
        for declaration in node.declarations:
            self.visit(declaration, scope.create_child())
        return scope

    @visitor.when(ClassDeclarationNode)
    def visit(self, node, scope):
        self.current_type = self.context.get_type(node.id)
        scope.define_variable('self', SelfType(self.current_type))
        attributes = self.current_type.all_attributes()
        for values in attributes:
            attr, _ = values
            scope.define_variable(attr.name, attr.type, attr.idx)
            
        for feature in node.features:
            self.visit(feature, scope.create_child())
           
    @visitor.when(AttrDeclarationNode)
    def visit(self, node, scope):
        var = scope.find_variable(node.id)
        attr_type = var.type

        if node.expr is not None:
            computed_type = self.visit(node.expr, scope)
            if not self.check_conformance(computed_type, attr_type):
                self.errors.append(INCOMPATIBLE_TYPES %(computed_type.name, attr_type.name))

    @visitor.when(FuncDeclarationNode)
    def visit(self, node, scope):
        self.current_method = self.current_type.get_method(node.id)
        
        # checking overwriting
        try:
            method = self.current_type.parent.get_method(node.id)
            if not len(self.current_method.param_types) == len(method.param_types):
                self.errors.append(WRONG_SIGNATURE %(node.id, self.current_type.name))
            else:
                for i, t in enumerate(self.current_method.param_types):
                    if not method.param_types[i] == t:
                        self.errors.append(WRONG_SIGNATURE %(node.id, self.current_type.name))
                        break
                else:
                    if not self.current_method.return_type == method.return_type:
                        self.errors.append(WRONG_SIGNATURE %(node.id, self.current_type.name))
        except SemanticError:
            pass
        
        # defining variables in new scope
        for i, var in enumerate(self.current_method.param_names):
            if scope.is_local(var):
                self.errors.append(LOCAL_ALREADY_DEFINED %(var, self.current_method.name))
            else:
                scope.define_variable(var, self.current_method.param_types[i], self.current_method.param_idx[i])
                
        computed_type = self.visit(node.body, scope)
        
        # checking return type
        rtype = self.current_method.return_type
        if not self.check_conformance(computed_type, rtype):
            self.errors.append(INCOMPATIBLE_TYPES %(computed_type.name, self.current_method.return_type.name))
            
    @visitor.when(AssignNode)
    def visit(self, node, scope):
        if node.id == "self":
            self.errors.append(SELF_IS_READONLY)
                
        # checking variable is defined
        var = scope.find_variable(node.id)
        if var is None:
            self.errors.append(VARIABLE_NOT_DEFINED %(node.id, self.current_type.name))
            var = scope.define_variable(node.id, ErrorType())
        
        computed_type = self.visit(node.expr, scope.create_child())
        
        if not self.check_conformance(computed_type, var.type):
            self.errors.append(INCOMPATIBLE_TYPES %(computed_type.name, var.type.name))
            
        return computed_type
          
    @visitor.when(CallNode)
    def visit(self, node, scope):
        # Evaluate object
        obj_type = self.visit(node.obj, scope)
        
        # Check object type conforms to cast type
        cast_type = obj_type
        if node.type is not None:
            try:
                cast_type = self.context.get_type(node.type)
                if isinstance(cast_type, AutoType):
                    raise SemanticError('AUTO_TYPE can\'t be the type on this type of dispatch')
                if isinstance(cast_type, SelfType):
                    cast_type = SelfType(self.current_type)
            except SemanticError as ex:
                cast_type = ErrorType()
                self.errors.append(ex.text)
        if not self.check_conformance(obj_type, cast_type):
            self.errors.append(INCOMPATIBLE_TYPES %(obj_type.name, cast_type.name))

        # if the obj that is calling the function is autotype, let it pass
        if isinstance(cast_type, AutoType):
            return cast_type

        if isinstance(cast_type, SelfType):
            cast_type = self.current_type
        
        # Check this function is defined for cast_type
        try:
            method = cast_type.get_method(node.id)
            if not len(node.args) == len(method.param_types):
                self.errors.append(INVALID_OPERATION %(method.name, cast_type.name))
                return ErrorType()
            for i, arg in enumerate(node.args):
                computed_type = self.visit(arg, scope)
                if not self.check_conformance(computed_type, method.param_types[i]):
                    self.errors.append(INCOMPATIBLE_TYPES %(computed_type.name, method.param_types[i].name))
            
            # check self_type
            rtype = method.return_type
            if isinstance(rtype, SelfType):
                rtype = obj_type

            return rtype

        except SemanticError as ex:
            self.errors.append(ex.text)
            return ErrorType()
        
    @visitor.when(CaseNode)
    def visit(self, node, scope):
        # check expression
        self.visit(node.expr, scope)

        nscope = scope.create_child()

        # check branches
        types = []
        node.branch_idx = []
        for branch in node.branch_list:
            idx, typex, expr =  branch
            
            node.branch_idx.append(None)
            
            # check idx is not self
            if idx == 'self':
                self.errors.append(SELF_IS_READONLY)

            try:
                var_type = self.context.get_type(typex)
                if isinstance(var_type, SelfType):
                    var_type = SelfType(self.current_type)
            except SemanticError as ex:
                self.errors.append(ex.text)
                var_type = ErrorType()
            
            # check type is autotype and assign an id in the manager
            if isinstance(var_type, AutoType):
                node.branch_idx[-1] = self.manager.assign_id(self.obj_type)

            new_scope = nscope.create_child()
            new_scope.define_variable(idx, var_type, node.branch_idx[-1])

            computed_type = self.visit(expr, new_scope)
            types.append(computed_type)

        return LCA(types)
    
    @visitor.when(BlockNode)
    def visit(self, node, scope):
        nscope = scope.create_child()

        # Check expressions
        computed_type = None
        for expr in node.expr_list:
            computed_type = self.visit(expr, nscope)

        # return the type of the last expression of the list
        return computed_type

    @visitor.when(LoopNode)
    def visit(self, node, scope):
        nscope = scope.create_child()

        # checking condition: it must conform to bool
        cond_type = self.visit(node.condition, nscope)
        if not cond_type.conforms_to(self.bool_type):
            self.errors.append(INCOMPATIBLE_TYPES %(cond_type.name, self.bool_type.name))

        # checking body
        self.visit(node.body, nscope)

        return self.obj_type

    @visitor.when(ConditionalNode)
    def visit(self, node, scope):

        # check condition conforms to bool
        cond_type = self.visit(node.condition, scope)
        if not cond_type.conforms_to(self.bool_type):
            self.errors.append(INCOMPATIBLE_TYPES %(cond_type.name, self.bool_type.name))

        then_type = self.visit(node.then_body, scope.create_child())
        else_type = self.visit(node.else_body, scope.create_child())

        return LCA([then_type, else_type])

    @visitor.when(LetNode)
    def visit(self, node, scope):
        nscope = scope.create_child()

        node.idx_list = [None] * len(node.id_list)
        for i, item in enumerate(node.id_list):
            idx, typex, expr = item
            # create a new_scope for every variable defined
            new_scope = nscope.create_child()
            
            if idx == 'self':
                self.errors.append(SELF_IS_READONLY)
                idx = f'1{idx}'
                node.id_list[i] = (idx, typex, expr)
            
            try:
                typex = self.context.get_type(typex)
                if isinstance(typex, SelfType):
                    typex = SelfType(self.current_type)
            except SemanticError as ex:
                self.errors.append(ex.text)
                typex = ErrorType()

            if isinstance(typex, AutoType):
                node.idx_list[i] = self.manager.assign_id(self.obj_type)

            if expr is not None:
                expr_type = self.visit(expr, new_scope)
                if not self.check_conformance(expr_type, typex):
                    self.errors.append(INCOMPATIBLE_TYPES %(expr_type.name, typex.name))

            new_scope.define_variable(idx, typex, node.idx_list[i])
            nscope = new_scope

        return self.visit(node.body, nscope)

    @visitor.when(ArithmeticNode)
    def visit(self, node, scope):
        self.check_expr(node, scope)
        return self.int_type

    @visitor.when(ComparisonNode)
    def visit(self, node, scope):
        self.check_expr(node, scope)
        return self.bool_type

    @visitor.when(EqualNode)
    def visit(self, node, scope):
        left = self.visit(node.left, scope)
        right = self.visit(node.right, scope)

        types = [self.int_type, self.bool_type, self.string_type]
        def check_equal(typex, other):
            for t in types:
                if typex.conforms_to(t):
                    if not other.conforms_to(t):
                        self.errors.append(INCOMPATIBLE_TYPES %(other.name, t.name))
                    return True
            return False

        ok = check_equal(left, right)
        if not ok:
            check_equal(right, left)
        
        return self.bool_type

    @visitor.when(VoidNode)
    def visit(self, node, scope):
        self.visit(node.expr, scope)
        
        return self.bool_type

    @visitor.when(NotNode)
    def visit(self, node, scope):
        typex = self.visit(node.expr, scope)
        if not typex.conforms_to(self.bool_type):
            self.errors.append(INCOMPATIBLE_TYPES %(typex.name, self.bool_type.name))
        
        return self.bool_type

    @visitor.when(NegNode)
    def visit(self, node, scope):
        typex = self.visit(node.expr, scope)
        if not typex.conforms_to(self.int_type):
            self.errors.append(INCOMPATIBLE_TYPES %(typex.name, self.int_type.name))
        
        return self.int_type

    @visitor.when(ConstantNumNode)
    def visit(self, node, scope):
        return self.int_type

    @visitor.when(ConstantBoolNode)
    def visit(self, node, scope):
        return self.bool_type

    @visitor.when(ConstantStringNode)
    def visit(self, node, scope):
        return self.string_type

    @visitor.when(VariableNode)
    def visit(self, node, scope):
        var = scope.find_variable(node.lex)
        if var is None:
            self.errors.append(VARIABLE_NOT_DEFINED %(node.lex, self.current_type.name))
            var = scope.define_variable(node.lex, ErrorType())

        return var.type

    @visitor.when(InstantiateNode)
    def visit(self, node, scope):
        try:
            typex = self.context.get_type(node.lex)
            if isinstance(typex, AutoType):
                raise SemanticError('AUTO_TYPE can\'t be instanciate with new')
            if isinstance(typex, SelfType):
                typex = SelfType(self.current_type)
        except SemanticError as ex:
            self.errors.append(ex.text)
            typex = ErrorType()
        
        return typex


    def check_expr(self, node, scope):
        # checking left expr
        left = self.visit(node.left, scope)
        if not left.conforms_to(self.int_type):
            self.errors.append(INCOMPATIBLE_TYPES %(left.name, self.int_type.name))

        # checking right expr
        right = self.visit(node.right, scope)
        if not right.conforms_to(self.int_type):
            self.errors.append(INCOMPATIBLE_TYPES %(right.name, self.int_type.name))

    def check_conformance(self, computed_type, attr_type):
        return (
            computed_type.conforms_to(attr_type)
            or (isinstance(computed_type, SelfType) and self.current_type.conforms_to(attr_type))
        )