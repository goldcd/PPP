##It all begins here...
import sys
from app.prerequisites import check_prerequisites   
def main():
    print("Welcome to PPP!")
    ##Check prerequisites and warn if not met - This was AI, so don't blame me if it doesn't work..
    check_prerequisites()
    
    ## Added some end points to allow processing to be run from CLI
    ## python main.py --process-all
    if len(sys.argv) > 1 and sys.argv[1] == "--process-all":
        from app.actions import call_process_all
        print("Running full process pipeline from CLI...")
        call_process_all()
        return

    from app.menu import Menu
    ##Initialize the menu object
    menu = Menu()
    ##Kick off the display of it
    menu.display_menu()



if __name__ == "__main__":
    main()