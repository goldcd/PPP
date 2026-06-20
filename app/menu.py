import json
import os
##os.system('cls' if os.name == 'nt' else 'clear')##Use this to clear the screen, but not sure where I want to do this yet
from app import actions

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

        ## Later on I want to add sub-menus to this, but..that's for another day

        ##Find out what they tried to trigger
        for selection in self.menu["root"]["options"]:
            if selection["key"] == choice:
                self.execute_selection(selection['action'])
        ##Now re-draw the menu
        self.display_menu()

    def execute_selection(self, action):
        print(f"Running {action}")
        ##Now see if this action is in actions.py
        func = getattr(actions, action, None)
        
        ##If it's a callable function, run it
        if func and callable(func):
            func()
        else:
            print(f"Action '{action}' is not defined in actions.py")
            