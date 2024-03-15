class NotFoundError(Exception):
    def __init__(self, info="Response <404>: File was not found in the url"):
        self.info = info
        super().__init__(self.info)

class EmptyMandatoryParameter(Exception):
    def __init__(self, info="Please fill in the mandatory parameters"):
        self.info = info
        super().__init__(self.info)