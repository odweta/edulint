def c_to_f(c):
    return c * 9 / 5 + 32

def f_to_c(f):
    return (f - 32) * 5 / 9

def convert_all(values, unit):
    out = []
    for v in values:
        if unit == "C":
            out.append(c_to_f(v))
        elif unit == "F":
            out.append(f_to_c(v))
    return out

temps = [0, 21.5, 37, 100]
for t in temps:
    print("%d C is %d F" % (t, c_to_f(t)))
x = convert_all(temps, "C")
x = x
print(x)
