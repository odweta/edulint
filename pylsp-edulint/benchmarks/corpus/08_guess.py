import random

secret = random.randint(1, 100)
tries = 0
while True:
    guess = int(input("Your guess: "))
    tries = tries + 1
    if guess < secret:
        print("too low")
    elif guess > secret:
        print("too high")
    else:
        print("correct after", tries, "tries")
        break
