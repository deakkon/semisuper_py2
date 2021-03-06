# coding=utf-8
from __future__ import absolute_import, division, print_function
print('ss_model_selection.py')
import multiprocessing as multi
import os
import time
from copy import deepcopy
from functools import partial
from itertools import product

import numpy as np
from sklearn.metrics import classification_report, precision_recall_fscore_support, accuracy_score
from sklearn.model_selection import train_test_split, KFold
from sklearn.pipeline import Pipeline
from sklearn.base import clone

from sklearn.naive_bayes import MultinomialNB
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression, SGDClassifier, Lasso
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC, LinearSVC
from sklearn.tree import DecisionTreeClassifier
print('ss_model_selection.py DONE WITH SZSTEM')
from semisuper import transformers, ss_techniques
from semisuper.helpers import num_rows, concatenate
print('ss_model_selection.py DONE WITH USER')

PARALLEL = True
# RANDOM_SEED = 135242  # for making different test runs comparable
RANDOM_SEED = np.random.randint(10e6)


# print("RANDOM SEED:", RANDOM_SEED, "\n") # TODO remove


# ----------------------------------------------------------------
# Estimators and parameters to evaluate
# ----------------------------------------------------------------

# TODO revert param ranges

def estimator_list():
    neg_svms = [{'name' : 'negLinSVC_C_{}_loss_{}'.format(C, loss),
                 'model': partial(ss_techniques.neg_self_training_clf,
                                  LinearSVC(C=C, loss=loss, class_weight='balanced'))}
                # for C in np.arange(0.2, 1.05, 0.1) for loss in ["squared_hinge"]]
                for C in np.arange(0.25, 0.65, 0.05) for loss in ["squared_hinge"]]

    neg_logits = [{'name' : 'negLogit_C_C{}'.format(C),
                   'model': partial(ss_techniques.neg_self_training_clf, LogisticRegression(solver='sag', C=C))}
                  for C in np.arange(1.0, 10.05, 1.0)]

    neg_nbs = [{'name': 'negNB_a_0.1', 'model': partial(ss_techniques.neg_self_training_clf, MultinomialNB(alpha=0.1))},
               {'name': 'negNB_a_0.5', 'model': partial(ss_techniques.neg_self_training_clf, MultinomialNB(alpha=0.5))},
               {'name': 'negNB_a_1.0', 'model': partial(ss_techniques.neg_self_training_clf, MultinomialNB(alpha=1.0))}]
    neg_sgds = [
        {'name' : 'negSGDmh',
         'model': partial(ss_techniques.neg_self_training_clf,
                          SGDClassifier(loss='modified_huber', class_weight='balanced'))},
        {'name' : 'negSGDpc',
         'model': partial(ss_techniques.neg_self_training_clf,
                          SGDClassifier(loss='perceptron', class_weight='balanced'))},
    ]

    self_logits = [{'name' : 'selfLogit_C_C{}'.format(C),
                    'model': partial(ss_techniques.self_training_clf_conf,
                                     LogisticRegression(solver='sag', C=C),
                                     0.75
                                     )}
                   for C in np.arange(1.0, 10.05, 1.0)]

    self_svms = [{'name' : 'selfLinSVC_C_{}_loss_{}'.format(C, loss),
                  'model': partial(ss_techniques.self_training_clf_conf,
                                   LinearSVC(C=C, loss=loss, class_weight='balanced'),
                                   0.5)}
                 for C in np.arange(0.2, 1.05, 0.1) for loss in ["squared_hinge"]]

    self_nbs = [
        {'name' : 'selfNB_a_0.1',
         'model': partial(ss_techniques.self_training_clf_conf, MultinomialNB(alpha=0.1), 0.75)},
        {'name' : 'selfNB_a_0.5',
         'model': partial(ss_techniques.self_training_clf_conf, MultinomialNB(alpha=0.5), 0.75)},
        {'name' : 'selfNB_a_1.0',
         'model': partial(ss_techniques.self_training_clf_conf, MultinomialNB(alpha=1.0), 0.75)},
    ]

    EM = [{'name': 'EM', 'model': ss_techniques.EM}]

    # NOTE: these require dense arrays, take a lot of time and RAM (set global PARALLEL to False!),
    # and don't work well on our data
    propagation = [
        {'name' : 'label_propagation_rbf',
         'model': partial(ss_techniques.label_propagation_method, "propagation", "rbf")},
        {'name' : 'label_propagation_knn',
         'model': partial(ss_techniques.label_propagation_method, "propagation", "knn")},
        {'name': 'label_spreading_rbf', 'model': partial(ss_techniques.label_propagation_method, "spreading", "rbf")},
        {'name': 'label_spreading_knn', 'model': partial(ss_techniques.label_propagation_method, "spreading", "knn")},
    ]

    # NOTE: only for comparison as a baseline
    supervised = [
        {'name': 'sup-nb', 'model': ss_techniques.nb},
        {'name': 'sup-lr', 'model': ss_techniques.logreg},
        {'name': 'sup-svm', 'model': ss_techniques.grid_search_linearSVM},
        {'name': 'sup-sgd', 'model': ss_techniques.sgd},

    ]

    return neg_svms
    # return self_logits + self_svms + self_nbs + neg_logits + neg_svms + neg_nbs


def preproc_param_dict():
    d = {
        'df_min'        : [0.002],  # [0.001, 0.002, 0.005, 0.01],
        'df_max'        : [1.0],
        'rules'         : [True],  # [False, True],
        'wordgram_range': [(1, 4)],  # [None, (1, 2), (1, 3), (1, 4)],
        'chargram_range': [(2, 6)],  # [None, (2, 4), (2, 5), (2, 6)],
        'feature_select': [
            # transformers.IdentitySelector,
            # partial(transformers.percentile_selector, 'chi2', 30),
            partial(transformers.percentile_selector, 'chi2', 25),
            # partial(transformers.percentile_selector, 'chi2', 20),
            # partial(transformers.select_from_l1_svc, 1.0, 1e-4),
            # partial(transformers.select_from_l1_svc, 0.5, 1e-4),
            # partial(transformers.select_from_l1_svc, 0.1, 1e-4),
        ]
    }

    return d


# ----------------------------------------------------------------
# Cross validation
# ----------------------------------------------------------------

def best_model_cross_val(P, N, U, fold=10):
    """determine best model, cross validate and return pipeline trained on all data"""

    print("\nFinding best model")

    best = get_best_model(P, N, U)['best']

    print("\nCross-validation\n")

    kf = KFold(n_splits=fold, shuffle=True)
    splits = zip(list(kf.split(P)), list(kf.split(N)))

    # TODO doesn't work in parallel
    # if PARALLEL:
    #     with multi.Pool(min(fold, multi.cpu_count())) as p:
    #         stats = list(p.map(partial(eval_fold, best, P, N, U), enumerate(splits), chunksize=1))
    # else:
    #     stats = list(map(partial(eval_fold, best, P, N, U), enumerate(splits)))
    stats = list(map(partial(eval_fold, best, P, N, U), enumerate(splits)))

    mean_stats = np.mean(stats, 0)
    print("Cross-validation average: p {}, r {}, f1 {}, acc {}".format(
            mean_stats[0], mean_stats[1], mean_stats[2], mean_stats[3]))

    print("Retraining model on full data")

    vec, sel = best['vectorizer'], best['selector']
    vec.fit(concatenate((P, N, U)))
    P_, N_, U_ = [vec.transform(x) for x in [P, N, U]]

    y_pp = concatenate((np.ones(num_rows(P)), -np.ones(num_rows(N)), np.zeros(num_rows(U))))
    sel.fit(concatenate((P_, N_, U_)), y_pp)
    P_, N_, U_ = [(sel.transform(x)) for x in [P_, N_, U_]]

    model = best['untrained_model'](P_, N_, U_)

    print("Ratio of U classified as positive:", np.sum(model.predict(U_)) / num_rows(U_))
    print("Returning final model")

    return Pipeline([('vectorizer', vec), ('selector', sel), ('clf', model)])


# helper
def eval_fold(model_record, P, N, U, i_splits):
    """helper function for running cross validation in parallel"""

    i, (p_split, n_split) = i_splits
    P_train, P_test = P[p_split[0]], P[p_split[1]]
    N_train, N_test = N[n_split[0]], N[n_split[1]]

    y_train_pp = concatenate((np.ones(num_rows(P_train)), -np.ones(num_rows(N_train)), np.zeros(num_rows(U))))
    pp = clone(Pipeline([('vectorizer', model_record['vectorizer']), ('selector', model_record['selector'])]))
    pp.fit(concatenate((P_train, N_train, U)), y_train_pp)

    P_, N_, U_, P_test_, N_test_ = [(pp.transform(x)) for x in [P_train, N_train, U, P_test, N_test]]
    model = model_record['untrained_model'](P_, N_, U_)

    y_pred = model.predict(concatenate((P_test_, N_test_)))
    y_test = concatenate((np.ones(num_rows(P_test_)), np.zeros(num_rows(N_test_))))

    pr, r, f1, _ = precision_recall_fscore_support(y_test, y_pred, average='weighted')
    acc = accuracy_score(y_test, y_pred)

    print("Fold no.", i, "acc", acc, "classification report:\n", classification_report(y_test, y_pred))
    return [pr, r, f1, acc]


# ----------------------------------------------------------------
# Model selection
# ----------------------------------------------------------------

def get_best_model(P_train, N_train, U_train, X_test=None, y_test=None):
    """Evaluate parameter combinations, save results and return object with stats of all models"""

    print("Evaluating parameter ranges for preprocessor and classifiers")

    if X_test is None or y_test is None:
        P_train, X_test_pos = train_test_split(P_train, test_size=0.2, random_state=RANDOM_SEED)
        N_train, X_test_neg = train_test_split(N_train, test_size=0.2, random_state=RANDOM_SEED)
        X_test = concatenate((X_test_pos, X_test_neg))
        y_test = concatenate((np.ones(num_rows(X_test_pos)), np.zeros(num_rows(X_test_neg))))

    X_train = concatenate((P_train, N_train, U_train))
    y_train_pp = concatenate((np.ones(num_rows(P_train)), -np.ones(num_rows(N_train)), np.zeros(num_rows(U_train))))

    results = {'best': {'f1': -1, 'acc': -1}, 'all': []}

    preproc_params = preproc_param_dict()
    estimators = estimator_list()

    for wordgram, chargram in product(preproc_params['wordgram_range'], preproc_params['chargram_range']):
        for r in preproc_params['rules']:
            for df_min, df_max in product(preproc_params['df_min'], preproc_params['df_max']):
                for fs in preproc_params['feature_select']:

                    if wordgram is None and chargram is None:
                        break

                    print("\n----------------------------------------------------------------",
                          "\nwords:", wordgram, "chars:", chargram, "feature selection:", fs,
                          "df_min, df_max:", df_min, df_max, "rules", r,
                          "\n----------------------------------------------------------------\n")

                    start_time = time.time()

                    X_train_, X_test_, vectorizer, selector = prepare_train_test(trainData=X_train, testData=X_test,
                                                                                 trainLabels=y_train_pp, rules=r,
                                                                                 wordgram_range=wordgram,
                                                                                 feature_select=fs,
                                                                                 chargram_range=chargram,
                                                                                 min_df_char=df_min, min_df_word=df_min,
                                                                                 max_df=df_max)
                    if selector:
                        P_train_, N_train_, U_train_ = [(selector.transform(vectorizer.transform(x)))
                                                        for x in [P_train, N_train, U_train]]
                    else:
                        P_train_, N_train_, U_train_ = [(vectorizer.transform(x))
                                                        for x in [P_train, N_train, U_train]]

                    # fit models
                    if PARALLEL:
                        # with multi.Pool(min(multi.cpu_count(), len(estimators))) as p:
                        p = multi.Pool(min(multi.cpu_count(), len(estimators)))
                        iter_stats = list(p.map(partial(model_eval_record,
                                                            P_train_, N_train_, U_train_, X_test_, y_test),
                                                    estimators, chunksize=1))
                    else:
                        iter_stats = list(map(partial(model_eval_record,
                                                      P_train_, N_train_, U_train_, X_test_, y_test),
                                              estimators))

                    # finalize records: remove model, add n-gram stats, update best
                    for m in iter_stats:
                        m['n-grams'] = {'word': wordgram, 'char': chargram},
                        m['rules'] = r,
                        m['df_min, df_max'] = (df_min, df_max)
                        m['fs'] = fs()
                        if m['acc'] > results['best']['acc']:
                            results['best'] = deepcopy(m)
                            results['best']['vectorizer'] = vectorizer
                            results['best']['selector'] = selector
                        m.pop('model', None)

                    results['all'].append(iter_stats)

                    print("Evaluated words:", wordgram, "chars:", chargram,
                          "rules:", r,
                          "feature selection:", fs, "min_df:", df_min,
                          "in %s seconds\n" % (time.time() - start_time))

                    print_reports(iter_stats)

    print_results(results)

    return results
    # return test_best(results, X_eval, y_eval)


# TODO obsolete, remove
def test_best(results, X_eval, y_eval):
    """helper function to evaluate best model on held-out set. returns full results of model selection"""

    best_model = results['best']['model']
    selector = results['best']['selector']
    vectorizer = results['best']['vectorizer']

    if selector:
        transformedTestData = (selector.transform(vectorizer.transform(X_eval)))
    else:
        transformedTestData = (vectorizer.transform(X_eval))

    y_pred = best_model.predict(transformedTestData)

    p, r, f, s = precision_recall_fscore_support(y_eval, y_pred, average='weighted')
    acc = accuracy_score(y_eval, y_pred)

    print("Testing best model on held-out test set:\n", results['best']['name'],
          results['best']['n-grams'], results['best']['fs'], "\n",
          'p={}\tr={}\tf1={}\tacc={}'.format(p, r, f, acc))

    results['best']['eval stats'] = [p, r, f, s, acc]

    return results


def prepare_train_test(trainData, testData, trainLabels, rules=True, wordgram_range=None, feature_select=None,
                       chargram_range=None, min_df_char=0.001, min_df_word=0.001, max_df=1.0):
    """prepare training and test vectors, vectorizer and selector for validating classifiers"""

    print("Fitting vectorizer, preparing training and test data")

    vectorizer = transformers.vectorizer(chargrams=chargram_range, min_df_char=min_df_char, wordgrams=wordgram_range,
                                         min_df_word=min_df_word, rules=rules, max_df=max_df)

    transformedTrainData = vectorizer.fit_transform(trainData)
    transformedTestData = vectorizer.transform(testData)

    print("No. of features:", transformedTrainData.shape[1])

    selector = None
    if feature_select is not None:
        selector = feature_select()
        selector.fit(transformedTrainData, trainLabels)
        transformedTrainData = selector.transform(transformedTrainData)
        transformedTestData = selector.transform(transformedTestData)

        print("No. of features after reduction:", transformedTrainData.shape[1], "\n")
    print()
    return transformedTrainData, transformedTestData, vectorizer, selector


def model_eval_record(P, N, U, X, y, m):
    """helper function for finding best model in parallel: evaluate model and return stat object. """

    untrained_model = m['model']
    model = m['model'](P, N, U)
    name = m['name']

    y_pred = model.predict(X)

    p, r, f1, _ = precision_recall_fscore_support(y, y_pred, average='weighted')
    acc = accuracy_score(y, y_pred)
    clsr = classification_report(y, y_pred)

    pos_ratio = np.sum(model.predict(U)) / num_rows(U)

    print("\n")
    # print("\n{}:\tacc: {},\tpositive ratio in U:{},\tclassification report:\n{}".format(name, acc, pos_ratio, clsr))
    return {'name' : name, 'p': p, 'r': r, 'f1': f1, 'acc': acc, 'clsr': clsr,
            'model': model, 'untrained_model': untrained_model, 'U_ratio': pos_ratio}


# ----------------------------------------------------------------
# Printing
# ----------------------------------------------------------------

def print_results(results):
    """helper function to print stat objects, starting with best model"""

    print("\n----------------------------------------------------------------\n")
    # print("\nAll stats:\n")
    # for r in results['all']:
    #     print_reports(r)

    print("Best:\n")
    best = results['best']
    print(best['name'], best['n-grams'], best['fs'],
          "\nrules", best['rules'], "df_min, df_max", best['df_min, df_max'],
          "\namount of U labelled as relevant:", best['U_ratio'],
          "\nstats: p={}\tr={}\tf1={}\tacc={}\t".format(best['p'], best['r'], best['f1'], best['acc']))

    print("\n----------------------------------------------------------------\n")
    return


def print_reports(i):
    """helper to print model stat object"""
    print(i[0]['n-grams'], i[0]['fs'],
          "\nrules", i[0]['rules'], "df_min, df_max", i[0]['df_min, df_max'])

    for m in i:
        print("\n{}:\tacc: {}, relevant ratio in U: {}, classification report:\n{}".format(
                m['name'], m['acc'], m['U_ratio'], m['clsr']))
    return


# ----------------------------------------------------------------
# helpers

def file_path(file_relative):
    """return the correct file path given the file's path relative to calling script"""
    return os.path.join(os.path.dirname(__file__), file_relative)
