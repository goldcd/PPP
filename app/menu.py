import json
import os
##os.system('cls' if os.name == 'nt' else 'clear')##Use this to clear the screen, but not sure where I want to do this yet


## Class to handle the menu interactions
class Menu():

    ##I'm just going to use one instance of this class for my menus
    ##When i initialize it, I want it to read in the menus.json file.
    def __init__(self):
        self.menu = json.load(open("config/menus.json"))

    def display_menu(self):
        ## Display the menu I've put in my menus.json
        for option in self.menu["root"]["options"]:
            print(f"{option['key']}: {option['label']}")
       
        ##Now make the user pick one
        choice = input("Enter your choice: ")

        ##Handle the choice
        self.get_selection(choice)
             

    def get_selection(self, choice):
        ## Check the menu file to ensure they've actually picked a valid option.
        valid_keys = [option["key"] for option in self.menu["root"]["options"]]

        if choice in valid_keys:
            print ("Hurrah, you're not a fuckwit!")
        else:
            print ("You are a fuckwit")
        
        ## For now, just re-draw the menu.
        ## Later on I want to add sub-menus to this, but..abs

        ##Now re-draw the menu
        self.display_menu()