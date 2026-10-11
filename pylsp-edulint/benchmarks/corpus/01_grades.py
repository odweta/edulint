import os
import sys

def average(l):
    sum = 0
    for i in range(len(l)):
        sum = sum + l[i]
    return sum / len(l)

def grade(score):
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    else:
        return "F"

scores = [95, 82, 71, 64, 100]
total = 0
for s in scores:
    total = total + s
print("Average:", average(scores))
for s in scores:
    print(s, grade(s))
if total > 400 == True:
    print("high")
