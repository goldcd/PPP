##File/module/whatever you're supposed to call them that handles incoming actions from the user menu.
##Small bits of logic can stay in here, but larger pieces will just call a dedicated module
##I now realize I probably should just have the logic the UI triggers here, and then pass items into the modules..
##As then these could be APIs... but a task for another day. Let's get this working first.

from app.RSS_Handler import add_RSS, view_RSS, delete_RSS
from app.download import download
from app.transcribe import transcribe_all

def call_add_RSS():
    add_RSS()

def call_view_RSS():
    view_RSS()

def call_delete_RSS():
    delete_RSS()

def call_download():
    download()

def call_transcribe():
    transcribe_all()

##First very simple action - just trigger this to close the app
def exit_app():
    print("Thank you. Come again!")
    exit()

def test_stub():
    print("""
    ________________________________________________________
    
        Imagine what exciting code could be here!!!
    ________________________________________________________
   
    """)
