from math import *

cart = {}
prices = {"apple": 0.5, "bread": 2.25, "milk": 1.2}

def add(item, qty=1, items=[]):
    items.append(item)
    if item in cart:
        cart[item] = cart[item] + qty
    else:
        cart[item] = qty
    return cart

def total():
    t = 0
    for item in cart:
        t += prices[item] * cart[item]
    return round(t, 2)

add("apple", 3)
add("milk")
print("Total:", total())
list = [1, 2, 3]
print(list)
