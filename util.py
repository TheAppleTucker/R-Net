import tensorflow as tf
import numpy as np
import re
from collections import Counter
import string


def get_record_parser(config, is_test=False):
    def parse(example):
        para_limit = config.test_para_limit if is_test else config.para_limit
        ques_limit = config.test_ques_limit if is_test else config.ques_limit
        char_limit = config.char_limit
        features = tf.parse_single_example(example,
                                           features={
                                               "context_idxs": tf.FixedLenFeature([], tf.string),
                                               "ques_idxs": tf.FixedLenFeature([], tf.string),
                                               "context_char_idxs": tf.FixedLenFeature([], tf.string),
                                               "ques_char_idxs": tf.FixedLenFeature([], tf.string),
                                               "y1": tf.FixedLenFeature([], tf.string),
                                               "y2": tf.FixedLenFeature([], tf.string),
                                               "id": tf.FixedLenFeature([], tf.int64)
                                           })
        context_idxs = tf.reshape(tf.decode_raw(
            features["context_idxs"], tf.int32), [para_limit])
        ques_idxs = tf.reshape(tf.decode_raw(
            features["ques_idxs"], tf.int32), [ques_limit])
        context_char_idxs = tf.reshape(tf.decode_raw(
            features["context_char_idxs"], tf.int32), [para_limit, char_limit])
        ques_char_idxs = tf.reshape(tf.decode_raw(
            features["ques_char_idxs"], tf.int32), [ques_limit, char_limit])
        y1 = tf.reshape(tf.decode_raw(
            features["y1"], tf.float32), [para_limit])
        y2 = tf.reshape(tf.decode_raw(
            features["y2"], tf.float32), [para_limit])
        qa_id = features["id"]
#        if config.use_squad_v2:
#            ones = tf.ones([1], tf.int32)
#            context_idxs = tf.concat([ones, context_idxs], 0)
#            #ques_idxs = tf.concat([ones, context_idxs], 0)
#            ones = tf.ones([1, char_limit], tf.int32)
#            context_char_idxs = tf.concat([ones, context_char_idxs], 0)
#            #ques_char_idxs = tf.concat([ones, ques_char_idxs], 0)
#            zeros = tf.zeros([1], tf.float32)
#            y1 = tf.concat([zeros, y1], 0)
#            y2 = tf.concat([zeros, y2], 0)
            
            
            
        return context_idxs, ques_idxs, context_char_idxs, ques_char_idxs, y1, y2, qa_id
    return parse


def get_batch_dataset(record_file, parser, config):
    num_threads = tf.constant(config.num_threads, dtype=tf.int32)
    dataset = tf.data.TFRecordDataset(record_file).map(
        parser, num_parallel_calls=num_threads).shuffle(config.capacity).repeat()
    if config.is_bucket:
        buckets = [tf.constant(num) for num in range(*config.bucket_range)]

        def key_func(context_idxs, ques_idxs, context_char_idxs, ques_char_idxs, y1, y2, qa_id):
            c_len = tf.reduce_sum(
                tf.cast(tf.cast(context_idxs, tf.bool), tf.int32))
            buckets_min = [np.iinfo(np.int32).min] + buckets
            buckets_max = buckets + [np.iinfo(np.int32).max]
            conditions_c = tf.logical_and(
                tf.less(buckets_min, c_len), tf.less_equal(c_len, buckets_max))
            bucket_id = tf.reduce_min(tf.where(conditions_c))
            return bucket_id

        def reduce_func(key, elements):
            return elements.batch(config.batch_size)

        dataset = dataset.apply(tf.contrib.data.group_by_window(
            key_func, reduce_func, window_size=5 * config.batch_size)).shuffle(len(buckets) * 25)
    else:
        dataset = dataset.batch(config.batch_size)
    return dataset


def get_dataset(record_file, parser, config):
    num_threads = tf.constant(config.num_threads, dtype=tf.int32)
    dataset = tf.data.TFRecordDataset(record_file).map(
        parser, num_parallel_calls=num_threads).repeat().batch(config.batch_size)
    return dataset


def convert_tokens(eval_file, qa_id, pp1, pp2, no_answer):
    answer_dict = {}
    remapped_dict = {}
    for qid, p1, p2 in zip(qa_id, pp1, pp2):
        context = eval_file[str(qid)]["context"]
        spans = eval_file[str(qid)]["spans"]
        uuid = eval_file[str(qid)]["uuid"]
        if no_answer and (p1 == 0 or p2 == 0):
            answer_dict[str(qid)] = ''
            remapped_dict[uuid] = ''
        else:
            if no_answer:
                p1, p2 = p1 - 1, p2 - 1
            start_idx = spans[p1][0]
            end_idx = spans[p2][1]
            answer_dict[str(qid)] = context[start_idx: end_idx]
            remapped_dict[uuid] = context[start_idx: end_idx]
    return answer_dict, remapped_dict


def evaluate(eval_file, answer_dict, no_answer):
    avna = f1 = exact_match = total = 0
    for key, value in answer_dict.items():
        total += 1
        ground_truths = eval_file[key]["answers"]
        prediction = value
        exact_match += metric_max_over_ground_truths(
            exact_match_score, prediction, ground_truths)
        f1 += metric_max_over_ground_truths(f1_score,
                                            prediction, ground_truths)
        if no_answer:
            avna += compute_avna(prediction, ground_truths)
        
    eval_dict = {'exact_match' : 100.0 * exact_match / total, 
                 'f1': 100.0 * f1 / total}
    
    if no_answer:
        eval_dict['AvNA'] = 100.0 * avna / total
    
    return eval_dict

def compute_avna(prediction, ground_truths):
    """Compute answer vs. no-answer accuracy."""
    return float(bool(prediction) == bool(ground_truths))

def normalize_answer(s):

    def remove_articles(text):
        return re.sub(r'\b(a|an|the)\b', ' ', text)

    def white_space_fix(text):
        return ' '.join(text.split())

    def remove_punc(text):
        exclude = set(string.punctuation)
        return ''.join(ch for ch in text if ch not in exclude)

    def lower(text):
        return text.lower()

    return white_space_fix(remove_articles(remove_punc(lower(s))))

def get_tokens(s):
    if not s:
        return []
    return normalize_answer(s).split()

def f1_score(prediction, ground_truth):
    prediction_tokens = get_tokens(prediction)
    ground_truth_tokens = get_tokens(ground_truth)
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if len(prediction_tokens) == 0 or len(ground_truth_tokens) == 0:
        return int(prediction_tokens == ground_truth_tokens)
    
    if num_same == 0:
        return 0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1


def exact_match_score(prediction, ground_truth):
    a = normalize_answer(prediction)
    b = normalize_answer(ground_truth)
    if(a == ''):
        a = "NO ANSWER"
    if(b == ''):
        b = "NO ANSWER"
    print(a, '|', b)
    
    return (normalize_answer(prediction) == normalize_answer(ground_truth))


def metric_max_over_ground_truths(metric_fn, prediction, ground_truths):
    if not ground_truths:
        return metric_fn(prediction, '')
    scores_for_ground_truths = []
    for ground_truth in ground_truths:
        score = metric_fn(prediction, ground_truth)
        scores_for_ground_truths.append(score)
    return max(scores_for_ground_truths)
