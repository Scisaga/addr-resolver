import logging
from flask_socketio import SocketIO

class WebSocketHandler(logging.Handler):
    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def emit(self, record):
        msg = self.format(record)
        self.socketio.emit('log', {'message': msg}, namespace='/logs')