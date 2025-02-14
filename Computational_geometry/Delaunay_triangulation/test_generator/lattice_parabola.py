import sys
import random
import math

if len(sys.argv) == 2:
    n = int(sys.argv[1])
else:
    print "Usage:\n  {0} <Number of points>".format(sys.argv[0])
    sys.exit(0)

range_max = 20000
coef = 1.0 / 20000
for i in xrange(n):
    x = int(round(random.uniform(0, range_max)))
    y = int(round(coef * x ** 2))
    print x, y

# vim: set ts=4 sw=4 et: 
