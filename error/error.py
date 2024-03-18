import xml.etree.ElementTree as et

class NotFoundError(Exception):
    def __init__(self, info="Response <404>: File was not found in the url"):
        self.info = info
        super().__init__(self.info)

class NoDataAvailable(Exception):
    def __init__(self, info="No data avaiable"):
        self.info = info
        super().__init__(self.info)

class ResponseApiCheck:

    def __init__(self, response) -> None:
        self.check_status(response.status_code)
        self.check_error(response.content) 

    @classmethod
    def check_status(self, status_code):
        if status_code == 404:
            raise NotFoundError
        
    @classmethod
    def check_error(self, content):
        message = False
        
        tree = et.ElementTree(et.fromstring(content))
        root = tree.getroot()
        for table in root.iter('ErrorTable'):
            message = table.find('Error').text

        if message:
            raise NoDataAvailable(message)



