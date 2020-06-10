import os
import socket
import sys
import json

class Pineapple:
    def __init__(self):
        self.debugOutput = os.environ.get("PINELIB_DEBUG")
        self.BLUE = '\033[94m'
        self.GREEN = '\033[92m'
        self.WARN = '\033[93m'
        self.ERROR = '\033[91m'
        self.ENDC = '\033[0m'

        self.moduleSocket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.moduleSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.moduleSocketPath = ""

    def debug(self, level, message):
        prefix = "[?] "
        if level == "INFO":
            prefix = self.BLUE + "[*] "
        elif level == "WARN":
            prefix = self.WARN + "[!] "
        elif level == "ERROR":
            prefix = self.ERROR + "[!!] "

        if self.debugOutput or level == "ERROR":
            print(self.GREEN + "[LIB]" + prefix + message + self.ENDC)

    def Init(self, moduleName):
        self.debug("INFO", "Pineapple Library Init")

        self.moduleSocketPath = "/tmp/" + moduleName + ".sock"

        try:
            os.unlink(self.moduleSocketPath)
        except OSError:
            if os.path.exists(self.moduleSocketPath):
                self.debug("ERROR", "Could not remove existing socket!")
                raise

        self.moduleSocket.bind(self.moduleSocketPath)
        self.debug("INFO", "Binding to socket: %s" % (self.moduleSocketPath))
        self.moduleSocket.listen(1)
        self.debug("INFO", "Listening on socket")

    def Receieve(self):
        connection, _ = self.moduleSocket.accept()
        data = connection.recv(4096)
        decodedData = data.decode('utf-8')

        dataDict = {}

        try:
            dataDict = json.loads(decodedData)
            self.debug("INFO", "Receieved Valid JSON")
            self.debug("INFO", "Module Name: %s" % (dataDict["module"]))
            self.debug("INFO", "Module Action: %s" % (dataDict["action"]))
        except ValueError:
            self.debug("WARN", "Non-JSON Receieved")

        return dataDict

    def Respond(self, message):
        bytesMessage = ''.encode('utf-8')
        messageType = type(message)

        byteMessage = self.messageToBytes(message)

        self.debug("INFO", "Sending Response: %s" % (str(byteMessage, "utf-8")))

        connection, _ = self.moduleSocket.accept()
        try:
            connection.sendall(byteMessage)
        except ValueError:
            self.debug("ERROR", "Could not send response!")
        else:
            self.debug("INFO", "Responded")

    def messageToBytes(self, message):
        self.debug("INFO", "Handling Module Response")
        self.debug("WARN", "Converting %s response to bytes" % (str(type(message).__name__)))

        d = json.dumps(message)

        return d.encode('utf-8')
