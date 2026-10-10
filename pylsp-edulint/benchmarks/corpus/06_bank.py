class Account:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance
        return None

    def deposit(self, amount):
        if amount <= 0:
            print("invalid amount")
            return
        self.balance += amount

    def withdraw(self, amount):
        if amount > self.balance:
            print("insufficient funds")
            return False
        else:
            self.balance -= amount
            return True

    def report(self):
        print(self.owner + ": " + str(self.balance))

    def report(self):
        print(f"{self.owner} has {self.balance}")


acc = Account("Ann", 100)
acc.deposit(50)
acc.withdraw(500)
acc.report()
