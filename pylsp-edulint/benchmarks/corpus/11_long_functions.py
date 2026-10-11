import json, os

def process(path):
    f = open(path)
    data = json.load(f)
    f.close()
    names = []
    ages = []
    cities = []
    for item in data:
        names.append(item["name"])
        ages.append(item["age"])
        cities.append(item["city"])
    result = {}
    for i in range(len(names)):
        result[names[i]] = (ages[i], cities[i])
    older = []
    for n in result:
        if result[n][0] > 30:
            older.append(n)
    younger = []
    for n in result:
        if result[n][0] <= 30:
            younger.append(n)
    print("older:", older)
    print("younger:", younger)
    by_city = {}
    for n in result:
        c = result[n][1]
        if c not in by_city:
            by_city[c] = []
        by_city[c].append(n)
    for c in by_city:
        print(c, len(by_city[c]))
    return result

if __name__ == "__main__":
    process("data.json")
