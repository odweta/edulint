def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)


def fib_iter(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def table(n):
    rows = []
    for i in range(n):
        rows.append((i, fib(i), fib_iter(i)))
    return rows


for row in table(15):
    print("{:>3} {:>5} {:>5}".format(*row))
def last():
    return 1
