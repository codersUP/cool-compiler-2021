import cmp.visitor as visitor
from cmp.ast import ProgramNode, ClassDeclarationNode, AttrDeclarationNode, FuncDeclarationNode
from cmp.semantic import SemanticError, ErrorType, InferencerManager, AutoType, SelfType


SELF_IS_READONLY = 'Variable "self" is read-only.'


class TypeBuilder:
    def __init__(self, context, errors=[]):
        self.context = context
        self.current_type = None
        self.errors = errors
        self.manager = InferencerManager()
        
        self.obj_type = self.context.get_type('Object')

    
    @visitor.on('node')
    def visit(self, node):
        pass
    
    
    @visitor.when(ProgramNode)
    def visit(self, node):
        for dec in node.declarations:
            self.visit(dec)

        self.check_main_class()
    
    @visitor.when(ClassDeclarationNode)
    def visit(self, node):
        self.current_type = self.context.get_type(node.id)
        for feat in node.features:
            self.visit(feat)
            
    @visitor.when(FuncDeclarationNode)
    def visit(self, node):
        ## Building param-names and param-types of the method
        param_names = []
        param_types = []
        node.index = []
        for param in node.params:
            n, t = param
            node.index.append(None)

            # Checking param name can't be self
            if n == "self":
                self.errors.append(SELF_IS_READONLY)

            while True:
                if n in param_names:
                    n = f'1{n}'
                else:
                    param_names.append(n)
                    break
                    
            try:
                t = self.context.get_type(t)
                if isinstance(t, SelfType):
                    t = SelfType(self.current_type)
                elif isinstance(t, AutoType):
                    node.index[-1] = self.manager.assign_id(self.obj_type)
            except SemanticError as ex:
                self.errors.append(ex.text)
                t = ErrorType()
            param_types.append(t)
        
        # Checking return type
        try:
            rtype = self.context.get_type(node.type)
            if isinstance(rtype, SelfType):
                rtype = SelfType(self.current_type)
        except SemanticError as ex:
            self.errors.append(ex.text)
            rtype = ErrorType()
        
        node.idx = self.manager.assign_id(self.obj_type) if isinstance(rtype, AutoType) else None
        
        # Defining the method in the current type. There can not be another method with the same name.
        try:
            self.current_type.define_method(node.id, param_names, param_types, rtype, node.index, node.idx)
        except SemanticError as ex:
            self.errors.append(ex.text)
            
    @visitor.when(AttrDeclarationNode)
    def visit(self, node):
        # Checking attribute type
        try:
            attr_type = self.context.get_type(node.type)
            if isinstance(attr_type, SelfType):
                attr_type = SelfType(self.current_type)
        except SemanticError as ex:
            self.errors.append(ex.text)
            attr_type = ErrorType()

        node.idx = self.manager.assign_id(self.obj_type) if isinstance(attr_type, AutoType) else None

        #Checking attribute can't be named self
        if node.id == "self":
            self.errors.append(SELF_IS_READONLY)
        
        # Checking attribute name. No other attribute can have the same name
        flag = False
        try:
            self.current_type.define_attribute(node.id, attr_type, node.idx)
            flag = True
        except SemanticError as ex:
            self.errors.append(ex.text)
        
        while not flag:
            node.id = f'1{node.id}'
            try:
                self.current_type.define_attribute(node.id, attr_type, node.idx)
                flag = True
            except SemanticError:
                pass


    def check_main_class(self):
        try:
            typex = self.context.get_type('Main')
            if not any(method.name == 'main' for method in typex.methods):
                self.errors.append('Class Main must contain a method main')
        except SemanticError:
            self.errors.append('Program must contain a class Main')