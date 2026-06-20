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
        ## The current menu state - starts at the root, but want to change this to let people drill down
        self.depth = self.menu["root"]
        self.last_error = None

    def display_menu(self):
        
        ## Putting the menu in a while loop. Previously I was recursively calling this function. But this is a lot cleaner
        while True:
            #Clear the screen
            os.system('cls' if os.name == 'nt' else 'clear')

            ##If a previous attempt to do something raised an error - show it here, then clear it
            if self.last_error:
                print(f"Error: {self.last_error}")
                self.last_error = None

            ## Display the menu I've put in my menus.json
            for option in self.depth["options"]:
                print(f"{option['key']}: {option['label']}")

            ## If we've moved from the initial root set, inject an extra option at the bottom to go back to the root menu
            if (self.depth != self.menu["root"]):
                print("0: Go back to main menu")
        
            ##Now make the user pick one
            choice = input("Enter your choice: ")

            ##Handle the choice
            self.get_selection(choice)
             

    def get_selection(self, choice):
        
        ## A bit hacky, but we're going to assume if they enter a 0, they want to go back to the main menu
        if choice == "0":
            self.depth = self.menu["root"]
            return
        ## If it wasn't a 0, then just go on as we did before, actually drilling down and seeing what they selected
        
        ## Check the menu file to see what the current valid options are for the user
        valid_keys = [option["key"] for option in self.depth["options"]]

        ##If the user can't pick a valid option, they deserve a crash, but I'll be nice
        if choice not in valid_keys:
            self.last_error=f"Invalid choice: {choice}"
            return

        ##Find out what they tried to trigger
        for selection in self.depth["options"]:
            if selection["key"] == choice:
                ##If we find an action, then we should execute it 
                if selection.get('action'):
                    ## Try to execute this
                    self.execute_selection(selection['action'])
                elif selection.get('options'):
                    #Update our position in the menu structure
                    self.depth = selection
                else:
                    self.last_error=f"We seem to have a menu issue where we have no actions or sub-options"

    def execute_selection(self, action):
        print(f"Running {action}")
        ##Now see if this action is in actions.py
        func = getattr(actions, action, None)
        
        ##If it's a callable function, run it
        if func and callable(func):
            func()
            #If we run something that might generate output, we should let the user see this, before we return to the menu loop (which will refresh the screen)
            input("\nPress Enter to continue")
        else:
            self.last_error=f"Action '{action}' is not defined in actions.py"
            