def make_matrix(n, m):
    matrix = []
    for i in range(n):
        row = []
        for j in range(m):
            row.append(i * j)
        matrix.append(row)
    return matrix


def transpose(matrix):
    result = []
    for j in range(len(matrix[0])):
        row = []
        for i in range(len(matrix)):
            row.append(matrix[i][j])
        result.append(row)
    return result


def print_matrix(matrix):
    for row in matrix:
        line = ""
        for x in row:
            line = line + str(x) + " "
        print(line)


m = make_matrix(3, 4)
print_matrix(m)
print_matrix(transpose(m))
unused = 42
