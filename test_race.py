import threading
from time import sleep

def check_race():
    print("Race condition exists if publish overwrites newer projection.")

check_race()
