import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from app_controller import AppController

if __name__ == "__main__":
    root = tk.Tk()
    app = AppController(root)
    root.mainloop()
