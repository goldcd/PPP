##It all begins here...
from app.menu import Menu

def main():
    print("Welcome to PPP!")
    ##Initialize the menu object
    menu = Menu()
    ##Kick off the display of it
    menu.display_menu()



if __name__ == "__main__":
    main()