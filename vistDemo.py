# coding=utf-8
from __future__ import absolute_import, division, print_function

# import cPickle as pickle
# import os
# import time
# import multiprocessing
# from tqdm import tqdm
# import random
# from itertools import cycle
#
# from semisuper import loaders, helpers

# READ MEDLINE
import pubmed_parser as pp
path = '/home/docClass/files/pubmed/pubmed18n0011.xml.gz'
articles = pp.parse_medline_xml(path)
print("read medline file")

# PREDICTOR
print("importing predictor")
import key_sentence_predictor
print("imported predictor")
predictor = key_sentence_predictor.KeySentencePredictor(batch_size=len(dictOut))
print("created keysentencepredictor object")

predicted = predictor.transform_batch(dictOut)
print(predicted, type(predicted))

scores = [x[2] in v for k,v in predicted.items() for x in v]
print(scores)
