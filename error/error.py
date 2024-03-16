from lxml import etree

class NotFoundError(Exception):
    def __init__(self, info="Response <404>: File was not found in the url"):
        self.info = info
        super().__init__(self.info)

class NoDataAvailable(Exception):
    def __init__(self, info="No data avaiable"):
        self.info = info
        super().__init__(self.info)

class Check:

    def __init__(self, content) -> None:
        self.check_error(content) 

    def check_error(self, content):
        message = False
        root = etree.fromstring(content)
        for table in root.findall(".//ErrorTable"):
            message = table.findtext('Error')

        if message:
            raise NoDataAvailable(message)

