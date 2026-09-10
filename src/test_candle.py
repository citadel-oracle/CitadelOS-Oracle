from candle_builder import CandleBuilder
import random
import time

builder = CandleBuilder()

price = 24260

while True:

    price += random.uniform(-2, 2)

    candle = builder.update(round(price, 2))

    if candle:

        print()

        print("New Candle")

        print(candle)

    time.sleep(1)