f = open('multiply.in.txt', 'r')
m, n = f.read().split(" ")
f2 = open('/tmp/grader/multiply.out.txt', 'w')
f2.write(str(int(m)*int(n)))
f2.close()

