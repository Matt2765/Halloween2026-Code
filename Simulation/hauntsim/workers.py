from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int,int)

    def __init__(self,function,parent=None):
        super().__init__(parent)
        self.function=function

    def run(self):
        try:
            self.result.emit(self.function(self.isInterruptionRequested,self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))
