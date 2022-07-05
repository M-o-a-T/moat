# dummy fs module on the multiplexer

from moat.cmd import BaseCmd

class FsCmd(BaseCmd):
	def __init__(self, parent, batt, name):
		super().__init__(parent)

