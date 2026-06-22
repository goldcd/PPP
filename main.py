##It all begins here...
from app.prerequisites import check_prerequisites   
def main():
    print("Welcome to PPP!")
    ##Check prerequisites and warn if not met - This was AI, so don't blame me if it doesn't work..
    check_prerequisites()
    
    ## Deferred import to prevent PyTorch DLLs from loading before potential uninstall
    from app.menu import Menu
    ##Initialize the menu object
    menu = Menu()
    ##Kick off the display of it
    menu.display_menu()



if __name__ == "__main__":
    main()