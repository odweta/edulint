def is_prime(n):
    if n < 2:
        return False
    for i in range(2, n):
        if n % i == 0:
            return False
            break
    else:
        return True

def primes_up_to(limit):
    result = []
    i = 2
    while True:
        if i > limit:
            break
        if is_prime(i) == True:
            result.append(i)
        i += 1
    return result

def main():
    limit = int(input("Limit: "))
    print(primes_up_to(limit))
main()
