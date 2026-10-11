students = []

def add_student(name, age, grade):
    students.append({"name": name, "age": age, "grade": grade})

def best_student():
    best = students[0]
    for s in students:
        if s["grade"] > best["grade"]:
            best = s
    return best

def average_age():
    total = 0
    count = 0
    for s in students:
        total += s["age"]
        count += 1
    return total / count

def is_adult(s):
    if s["age"] >= 18:
        return True
    else:
        return False

add_student("Ann", 19, 1.3)
add_student("Bob", 17, 2.0)
add_student("Cyril", 21, 1.0)
print(best_student()["name"])
print(average_age())
for s in students:
    print(s["name"], is_adult(s))
