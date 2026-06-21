##It all begins here...
from app.menu import Menu
from app.prerequisites import check_prerequisites   

def main():
    print("Welcome to PPP!")
    ##Check prerequisites and warn if not met - This was AI, so don't blame me if it doesn't work..
    print("AI slop will check for pre-requsisites now\n")
    check_prerequisites()
    ##Initialize the menu object
    menu = Menu()
    ##Kick off the display of it
    menu.display_menu()



if __name__ == "__main__":
    main()