import timeit
from datetime import datetime

# Setup mock data for benchmark
items = [{'time_updated': 1672531200, 'visibility': 0, 'title': 'Test', 'publishedfileid': '123'}] * 1000

# Function with import inside loop
def import_inside():
    for item in items:
        from datetime import datetime
        ts = datetime.fromtimestamp(item['time_updated']).strftime('%Y-%m-%d %H:%M')

# Function with import outside loop
def import_outside():
    for item in items:
        ts = datetime.fromtimestamp(item['time_updated']).strftime('%Y-%m-%d %H:%M')

print("With import inside loop:", timeit.timeit(import_inside, number=1000))
print("With import outside loop:", timeit.timeit(import_outside, number=1000))
