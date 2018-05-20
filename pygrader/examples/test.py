f = open('in.txt', 'r')
m, n = f.read().split(" ")
print("hey there")
f2 = open('/tmp/grader/out.txt', 'w')
f2.write(str(int(m)*int(n)))
f2.close()

