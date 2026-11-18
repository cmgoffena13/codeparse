from tests.files_to_parse.python.file import FakeClass

# Symbol Call Reference
fake_class_instance = FakeClass()

# Used in import alias check
variable_in_another_file = "test"


# Base Classes Check - FakeClass is a base class
class AnotherClass(FakeClass):
    def another_method(self):
        return self.fake_data
