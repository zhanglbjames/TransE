# -*- coding: utf-8 -*-
import tensorflow as tf
import time
import argparse
import random
import numpy as np
import matplotlib.pyplot as plt
import os.path
import math
import timeit
from multiprocessing import JoinableQueue, Queue, Process
from collections import defaultdict
# import sys
# sys.path.append("../")

class TransE:
	@property
	def variables(self):
		return self.__variables

	@property
	def num_triple_train(self):
		return self.__num_triple_train

	@property
	def num_triple_test(self):
		return self.__num_triple_test

	@property
	def testing_data(self):
		return self.__triple_test

	@property
	def num_entity(self):
		return self.__num_entity

	@property
	def embedding_entity(self):
		return self.__embedding_entity


	@property
	def embedding_relation(self):
		return self.__embedding_relation

	@property
	def hr_t(self):
		return self.__hr_t

	@property
	def tr_h(self):
		return self.__tr_h


	def training_data_batch(self, batch_size = 512):
		n_triple = len(self.__triple_train)
		rand_idx = np.random.permutation(n_triple)
		start = 0
		while start < n_triple:
			start_t = timeit.default_timer()
			end = min(start+batch_size, n_triple)
			size = end - start
			train_triple_positive = np.asarray([ self.__triple_train[x] for x in  rand_idx[start:end]])
			train_triple_negative = []
			for t in train_triple_positive:
				replace_entity_id = np.random.randint(self.__num_entity)
				random_num = np.random.random()

				if self.__negative_sampling == 'unif':
					replace_head_probability = 0.5
				elif self.__negative_sampling == 'bern':
					replace_head_probability = self.__relation_property[t[1]]
				else:
					raise NotImplementedError("Dose not support %s negative_sampling" %self.__negative_sampling)

				if random_num<replace_head_probability:
					train_triple_negative.append((replace_entity_id, t[1],t[2]))
				else:
					train_triple_negative.append((t[0], t[1], replace_entity_id))

			start = end
			prepare_t = timeit.default_timer()-start_t

			yield train_triple_positive, train_triple_negative, prepare_t


	def __init__(self, data_dir, negative_sampling,learning_rate,
				 batch_size, max_iter, margin, dimension, norm, evaluation_size, regularizer_weight):
		# this part for data prepare
		self.__data_dir=data_dir
		self.__negative_sampling=negative_sampling
		self.__regularizer_weight = regularizer_weight
		self.__norm = norm

		self.__entity2id={}
		self.__id2entity={}
		self.__relation2id={}
		self.__id2relation={}

		self.__triple_train=[] #[(head_id, relation_id, tail_id),...]
		self.__triple_test=[]
		self.__triple_valid=[]
		self.__triple = []

		self.__num_entity=0
		self.__num_relation=0
		self.__num_triple_train=0
		self.__num_triple_test=0
		self.__num_triple_valid=0

		# load all the file: entity2id.txt, relation2id.txt, train.txt, test.txt, valid.txt
		self.load_data()
		print('finish preparing data. ')


		# this part for the model:
		self.__learning_rate = learning_rate
		self.__batch_size = batch_size
		self.__max_iter = max_iter
		self.__margin = margin
		self.__dimension = dimension
		self.__variables= []
		#self.__norm = norm
		self.__evaluation_size = evaluation_size
		bound = 6 / math.sqrt(self.__dimension)
		with tf.device('/cpu'):
			self.__embedding_entity = tf.get_variable('embedding_entity', [self.__num_entity, self.__dimension],
													  initializer=tf.random_uniform_initializer(minval=-bound, maxval=bound, seed = 123))
			self.__embedding_relation = tf.get_variable('embedding_relation', [self.__num_relation, self.__dimension],
														initializer=tf.random_uniform_initializer(minval=-bound, maxval=bound, seed =124))
			self.__variables.append(self.__embedding_entity)
			self.__variables.append(self.__embedding_relation)
			print('finishing initializing')



	def load_data(self):
		print('loading entity2id.txt ...')
		with open(os.path.join(self.__data_dir, 'entity2id.txt')) as f:
			self.__entity2id = {line.strip().split('\t')[0]: int(line.strip().split('\t')[1]) for line in f.readlines()}
			self.__id2entity = {value:key for key,value in self.__entity2id.items()}


		with open(os.path.join(self.__data_dir,'relation2id.txt')) as f:
			self.__relation2id = {line.strip().split('\t')[0]: int(line.strip().split('\t')[1]) for line in f.readlines()}
			self.__id2relation = {value:key for key, value in self.__relation2id.items()}

		def load_triple(self, triplefile):
			triple_list = [] #[(head_id, relation_id, tail_id),...]
			with open(os.path.join(self.__data_dir, triplefile)) as f:
				for line in f.readlines():
					line_list = line.strip().split('\t')
					assert len(line_list) == 3
					headid = self.__entity2id[line_list[0]]
					relationid = self.__relation2id[line_list[2]]
					tailid = self.__entity2id[line_list[1]]
					triple_list.append((headid, relationid, tailid))
					self.__hr_t[(headid, relationid)].add(tailid)
					self.__tr_h[(tailid, relationid)].add(headid)
			return triple_list

		self.__hr_t = defaultdict(set)
		self.__tr_h = defaultdict(set)
		self.__triple_train = load_triple(self, 'train.txt')
		self.__triple_test = load_triple(self, 'test.txt')
		self.__triple_valid = load_triple(self, 'valid.txt')
		self.__triple = np.concatenate([self.__triple_train, self.__triple_test, self.__triple_valid], axis = 0 )

		self.__num_relation = len(self.__relation2id)
		self.__num_entity = len(self.__entity2id)
		self.__num_triple_train = len(self.__triple_train)
		self.__num_triple_test = len(self.__triple_test)
		self.__num_triple_valid = len(self.__triple_valid)

		print('entity number: ' + str(self.__num_entity))
		print('relation number: ' + str(self.__num_relation))
		print('training triple number: ' + str(self.__num_triple_train))
		print('testing triple number: ' + str(self.__num_triple_test))
		print('valid triple number: ' + str(self.__num_triple_valid))


		if self.__negative_sampling == 'bern':
			self.__relation_property_head = {x:[] for x in range(self.__num_relation)} #{relation_id:[headid1, headid2,...]}
			self.__relation_property_tail = {x:[] for x in range(self.__num_relation)} #{relation_id:[tailid1, tailid2,...]}
			for t in self.__triple_train:
				#print(t)
				self.__relation_property_head[t[1]].append(t[0])
				self.__relation_property_tail[t[1]].append(t[2])
			self.__relation_property = {x:(len(set(self.__relation_property_tail[x])))/(len(set(self.__relation_property_head[x]))+ len(set(self.__relation_property_tail[x]))) \
										for x in self.__relation_property_head.keys()} # {relation_id: p, ...} 0< num <1, and for relation replace head entity with the property p
		else:
			print("unif set do'n need to calculate hpt and tph")



	def train(self, inputs):
		embedding_relation = self.__embedding_relation
		embedding_entity = self.__embedding_entity

		triple_positive, triple_negative = inputs # triple_positive:(head_id,relation_id,tail_id)

		norm_entity = tf.nn.l2_normalize(embedding_entity, dim = 1)
		norm_relation = tf.nn.l2_normalize(embedding_relation, dim = 1)
		norm_entity_l2sum = tf.sqrt(tf.reduce_sum(norm_entity**2, axis = 1))

		embedding_positive_head = tf.nn.embedding_lookup(norm_entity, triple_positive[:, 0])
		embedding_positive_tail = tf.nn.embedding_lookup(norm_entity, triple_positive[:, 2])
		embedding_positive_relation = tf.nn.embedding_lookup(norm_relation, triple_positive[:, 1])

		embedding_negative_head = tf.nn.embedding_lookup(norm_entity, triple_negative[:, 0])
		embedding_negative_tail = tf.nn.embedding_lookup(norm_entity, triple_negative[:, 2])
		embedding_negative_relation = tf.nn.embedding_lookup(norm_relation, triple_negative[:, 1])

		score_positive = tf.reduce_sum(tf.abs(embedding_positive_head + embedding_positive_relation - embedding_positive_tail), axis = 1)
		score_negative = tf.reduce_sum(tf.abs(embedding_negative_head + embedding_negative_relation - embedding_negative_tail), axis = 1)

		loss_every = tf.maximum(0., score_positive + self.__margin - score_negative)
		loss_triple = tf.reduce_sum(tf.maximum(0., score_positive + self.__margin - score_negative))
		self.__loss_regularizer = loss_regularizer = tf.reduce_sum(tf.abs(self.__embedding_relation)) + tf.reduce_sum(tf.abs(self.__embedding_entity))
		return loss_triple, loss_every, norm_entity_l2sum #+ loss_regularizer*self.__regularizer_weight



	def test(self, inputs):
		embedding_relation = self.__embedding_relation
		embedding_entity = self.__embedding_entity

		triple_test = inputs # (headid, tailid, tailid)
		head_vec = tf.nn.embedding_lookup(embedding_entity, triple_test[0])
		rel_vec = tf.nn.embedding_lookup(embedding_relation, triple_test[1])
		tail_vec = tf.nn.embedding_lookup(embedding_entity, triple_test[2])

		norm_embedding_entity = tf.nn.l2_normalize(embedding_entity, dim =1 )
		norm_embedding_relation = tf.nn.l2_normalize(embedding_relation, dim = 1)
		norm_head_vec = tf.nn.embedding_lookup(norm_embedding_entity, triple_test[0])
		norm_rel_vec = tf.nn.embedding_lookup(norm_embedding_relation, triple_test[1])
		norm_tail_vec = tf.nn.embedding_lookup(norm_embedding_entity, triple_test[2])


		_, id_replace_head = tf.nn.top_k(tf.reduce_sum(tf.abs(embedding_entity + rel_vec - tail_vec), axis=1), k=self.__num_entity)
		_, id_replace_tail = tf.nn.top_k(tf.reduce_sum(tf.abs(head_vec + rel_vec - embedding_entity), axis=1), k=self.__num_entity)

		_, norm_id_replace_head = tf.nn.top_k(tf.reduce_sum(tf.abs(norm_embedding_entity + norm_rel_vec - norm_tail_vec), axis=1), k=self.__num_entity)
		_, norm_id_replace_tail = tf.nn.top_k(tf.reduce_sum(tf.abs(norm_head_vec + norm_rel_vec - norm_embedding_entity), axis=1), k=self.__num_entity)



		return id_replace_head, id_replace_tail, norm_id_replace_head, norm_id_replace_tail


def train_operation(model, learning_rate=0.01, margin=1.0, optimizer_str = 'gradient'):
	with tf.device('/cpu'):
		train_triple_positive_input = tf.placeholder(tf.int32, [None, 3])
		train_triple_negative_input = tf.placeholder(tf.int32, [None, 3])

		loss, loss_every, norm_entity = model.train([train_triple_positive_input, train_triple_negative_input])
		if optimizer_str == 'gradient':
			optimizer = tf.train.GradientDescentOptimizer(learning_rate = learning_rate)
		elif optimizer_str == 'rms':
			optimizer = tf.train.RMSPropOptimizer(learning_rate = learning_rate)
		elif optimizer_str == 'adam':
			optimizer = tf.train.AdamOptimizer(learning_rate = learning_rate)
		else:
			raise NotImplementedError("Dose not support %s optimizer" %optimizer_str)

		grads = optimizer.compute_gradients(loss, model.variables)
		op_train = optimizer.apply_gradients(grads)

		return train_triple_positive_input, train_triple_negative_input, loss, op_train, loss_every, norm_entity

def test_operation(model):
	with tf.device('/cpu'):
		test_triple = tf.placeholder(tf.int32, [3])
		print('finish palceholder')
		head_rank, tail_rank, norm_head_rank, norm_tail_rank = model.test(test_triple)
		print('finish model.test')
		return test_triple, head_rank, tail_rank, norm_head_rank, norm_tail_rank


def main():
	parser = argparse.ArgumentParser(description = "TransE")
	parser.add_argument('--data_dir', dest='data_dir', type=str, help='the directory of dataset', default='/home/mac/TransE_data/FB15k')
	parser.add_argument('--learning_rate', dest='learning_rate', type=float, help='learning rate', default=0.01)
	parser.add_argument('--batch_size', dest='batch_size', type=int, help="batch size", default=4096)
	parser.add_argument('--max_iter', dest='max_iter', type=int, help='maximum interation', default=100)
	parser.add_argument('--optimizer', dest='optimizer', type=str, help='optimizer', default='adam')
	parser.add_argument('--dimension', dest='dimension', type=int, help='embedding dimension', default=50)
	parser.add_argument('--margin', dest='margin', type=float, help='margin', default=1.0)
	parser.add_argument('--norm', dest='norm', type=str, help='L1 or L2 norm', default='L1')
	parser.add_argument('--evaluation_size', dest='evaluation_size', type=int, help='batchsize for evaluation', default=500)
	parser.add_argument('--save_dir', dest='save_dir', type=str, help='directory to save tensorflow checkpoint directory', default='output/')
	parser.add_argument('--negative_sampling', dest='negative_sampling', type=str, help='choose unit or bern to generate negative examples', default='bern')
	parser.add_argument('--evaluate_per_iteration', dest='evaluate_per_iteration', type=int, help='evaluate the training result per x iteration', default=10)
	parser.add_argument('--evaluate_worker', dest='evaluate_worker', type=int, help='number of evaluate workers', default=4)
	parser.add_argument('--regularizer_weight', dest='regularizer_weight', type=float, help='regularization weight', default=1e-5)
	parser.add_argument('--n_test', dest = 'n_test', type=int, help='number of triples for test during the training', default = 300)
	args = parser.parse_args()
	print(args)
	model = TransE(negative_sampling=args.negative_sampling, data_dir=args.data_dir,
				   learning_rate=args.learning_rate, batch_size=args.batch_size,
				   max_iter=args.max_iter, margin=args.margin,
				   dimension=args.dimension, norm=args.norm, evaluation_size=args.evaluation_size,
				   regularizer_weight = args.regularizer_weight)

	train_triple_positive_input, train_triple_negative_input, loss, op_train, loss_every, norm_entity = train_operation(model, learning_rate = args.learning_rate, margin = args.margin, optimizer_str = args.optimizer)
	test_triple, head_rank, tail_rank , norm_head_rank, norm_tail_rank= test_operation(model)


	with tf.Session() as session:
		tf.initialize_all_variables().run()

		norm_rel = session.run(tf.nn.l2_normalize(model.embedding_relation, dim =1))
		session.run(tf.assign(model.embedding_relation, norm_rel))
		norm_ent = session.run(tf.nn.l2_normalize(model.embedding_entity, dim =1))
		session.run(tf.assign(model.embedding_entity, norm_ent))

		# 定义画图数组
		all_loss=[]
		mean_rank=[]
		hit10=[]

		filter_mean_rank=[]
		filter_hit10=[]

		norm_mean_rank=[]
		norm_hit10=[]

		norm_filter_mean_rank=[]
		norm_filter_hit10=[]

		for n_iter in range(args.max_iter):
			all_loss_n_iter=[]
			accu_loss =0.
			batch = 0
			num_batch = model.num_triple_train/args.batch_size
			start_time = timeit.default_timer()
			prepare_time = 0.

			for tp, tn , t in  model.training_data_batch(batch_size= args.batch_size):
				l, _, l_every, norm_e = session.run([loss, op_train, loss_every, norm_entity], {train_triple_positive_input:tp, train_triple_negative_input: tn})
				accu_loss += l
				batch += 1
				print('[%.2f sec](%d/%d): -- loss: %.5f' %(timeit.default_timer()-start_time, batch, num_batch , l), end='\r')
				prepare_time += t
			all_loss_n_iter.append(accu_loss)
			print('iter[%d] ---loss: %.5f ---time: %.2f ---prepare time : %.2f' %(n_iter, accu_loss, timeit.default_timer()-start_time, prepare_time))

			# TODO
			#if n_iter %args.evaluate_per_iteration == 0 or n_iter ==0:
			if n_iter %args.evaluate_per_iteration == 0 or n_iter ==0 or n_iter == args.max_iter-1:
				#print("[iter %d] after l2 normalization the entity vectors: %s"%(n_iter, str(norm_e[:10])))
				#print("[iter %d] after training the entity vectors: %s"%(n_iter, str(session.run(tf.sqrt(tf.reduce_sum(model.embedding_entity**2, axis = 1))[:10]))))

				rank_head = []
				rank_tail = []
				filter_rank_head = []
				filter_rank_tail = []

				norm_rank_head = []
				norm_rank_tail = []
				norm_filter_rank_head = []
				norm_filter_rank_tail = []

				start = timeit.default_timer()
				testing_data = model.testing_data
				hr_t = model.hr_t
				tr_h = model.tr_h
				n_test = args.n_test
				if n_iter == args.max_iter-1:	n_test = model.num_triple_test
				for i in range(n_test):
					print('[%.2f sec] --- testing[%d/%d]' %(timeit.default_timer()-start, i+1, n_test), end='\r')
					t = testing_data[i]
					id_replace_head , id_replace_tail, norm_id_replace_head , norm_id_replace_tail  = session.run([head_rank, tail_rank, norm_head_rank, norm_tail_rank], {test_triple:t})
					hrank = 0
					fhrank = 0
					for i in range(len(id_replace_head)):
						val = id_replace_head[-i-1]
						if val == t[0]:
							break
						else:
							hrank += 1
							fhrank += 1
							if val in tr_h[(t[2],t[1])]:
								fhrank -= 1

					norm_hrank = 0
					norm_fhrank = 0
					for i in range(len(norm_id_replace_head)):
						val = norm_id_replace_head[-i-1]
						if val == t[0]:
							break
						else:
							norm_hrank += 1
							norm_fhrank += 1
							if val in tr_h[(t[2],t[1])]:
								norm_fhrank -= 1


					trank = 0
					ftrank = 0
					for i in range(len(id_replace_tail)):
						val = id_replace_tail[-i-1]
						if val == t[2]:
							break
						else:
							trank += 1
							ftrank += 1
							if val in hr_t[(t[0], t[1])]:
								ftrank -= 1

					norm_trank = 0
					norm_ftrank = 0
					for i in range(len(norm_id_replace_tail)):
						val = norm_id_replace_tail[-i-1]
						if val == t[2]:
							break
						else:
							norm_trank += 1
							norm_ftrank += 1
							if val in hr_t[(t[0], t[1])]:
								norm_ftrank -= 1

					rank_head.append(hrank)
					rank_tail.append(trank)
					filter_rank_head.append(fhrank)
					filter_rank_tail.append(ftrank)

					norm_rank_head.append(norm_hrank)
					norm_rank_tail.append(norm_trank)
					norm_filter_rank_head.append(norm_fhrank)
					norm_filter_rank_tail.append(norm_ftrank)

				mean_rank_head = np.sum(rank_head, dtype=np.float32)/n_test
				mean_rank_tail = np.sum(rank_tail, dtype=np.float32)/n_test
				filter_mean_rank_head = np.sum(filter_rank_head, dtype=np.float32)/n_test
				filter_mean_rank_tail = np.sum(filter_rank_tail, dtype=np.float32)/n_test

				norm_mean_rank_head = np.sum(norm_rank_head, dtype=np.float32)/n_test
				norm_mean_rank_tail = np.sum(norm_rank_tail, dtype=np.float32)/n_test
				norm_filter_mean_rank_head = np.sum(norm_filter_rank_head, dtype=np.float32)/n_test
				norm_filter_mean_rank_tail = np.sum(norm_filter_rank_tail, dtype=np.float32)/n_test

				hit10_head = np.sum(np.asarray(np.asarray(rank_head)<10 , dtype=np.float32))/n_test
				hit10_tail = np.sum(np.asarray(np.asarray(rank_tail)<10 , dtype=np.float32))/n_test
				filter_hit10_head = np.sum(np.asarray(np.asarray(filter_rank_head)<10 , dtype=np.float32))/n_test
				filter_hit10_tail = np.sum(np.asarray(np.asarray(filter_rank_tail)<10 , dtype=np.float32))/n_test

				norm_hit10_head = np.sum(np.asarray(np.asarray(norm_rank_head)<10 , dtype=np.float32))/n_test
				norm_hit10_tail = np.sum(np.asarray(np.asarray(norm_rank_tail)<10 , dtype=np.float32))/n_test
				norm_filter_hit10_head = np.sum(np.asarray(np.asarray(norm_filter_rank_head)<10 , dtype=np.float32))/n_test
				norm_filter_hit10_tail = np.sum(np.asarray(np.asarray(norm_filter_rank_tail)<10 , dtype=np.float32))/n_test

				#loss
				all_loss.append(sum(all_loss_n_iter)/len(all_loss_n_iter))

				mean_rank.append((mean_rank_head+ mean_rank_tail)/2)
				hit10.append(100*(hit10_tail+hit10_head)/2)
				print('iter:%d --mean rank: %.2f --hit@10: %.2f' %(n_iter, (mean_rank_head+ mean_rank_tail)/2, (hit10_tail+hit10_head)/2))
				filter_mean_rank.append((filter_mean_rank_head+ filter_mean_rank_tail)/2)
				filter_hit10.append(100*(filter_hit10_tail+filter_hit10_head)/2)
				print('iter:%d --filter mean rank: %.2f --filter hit@10: %.2f' %(n_iter, (filter_mean_rank_head+ filter_mean_rank_tail)/2, (filter_hit10_tail+filter_hit10_head)/2))

				norm_mean_rank.append((norm_mean_rank_head+ norm_mean_rank_tail)/2)
				norm_hit10.append(100*(norm_hit10_tail+norm_hit10_head)/2)
				print('iter:%d --norm mean rank: %.2f --norm hit@10: %.2f' %(n_iter, (norm_mean_rank_head+ norm_mean_rank_tail)/2, (norm_hit10_tail+norm_hit10_head)/2))
				norm_filter_mean_rank.append((norm_filter_mean_rank_head+ norm_filter_mean_rank_tail)/2)
				norm_filter_hit10.append(100*(norm_filter_hit10_tail+norm_filter_hit10_head)/2)
				print('iter:%d --norm filter mean rank: %.2f --norm filter hit@10: %.2f' %(n_iter, (norm_filter_mean_rank_head+ norm_filter_mean_rank_tail)/2, (norm_filter_hit10_tail+norm_filter_hit10_head)/2))
		#横坐标
		X = list(range(0,10*len(mean_rank),10))

		# offical
		offical_mean_rank_raw=[243.0 for i in range(0,len(mean_rank))]
		offical_mean_rank_filter=[125.0 for i in range(0,len(filter_mean_rank))]

		offical_hit10_raw=[34.9 for i in range(0,len(hit10))]
		offical_hit10_filter=[47.1 for i in range(0,len(filter_hit10))]

		#0
		plt.figure(figsize=(11, 11),dpi=80)
		plt.title('loss')
		plt.plot(X,np.array(all_loss),'-r',label='loss')
		plt.xlabel('epoch')
		plt.ylabel('loss')
		plt.legend()
		plt.savefig('./result_image/loss.png',dpi=80)
		plt.show()
		#1
		plt.figure(figsize=(11, 11),dpi=80)
		f,(fg1_raw,fg2_raw)=plt.subplots(2,1)

		#fg1_raw.set_title('mean rank')
		fg1_raw.set_xlabel('epoch')
		fg1_raw.set_ylabel('rank')
		fg1_raw.plot(X,np.array(mean_rank),'-r',label='raw mean rank')
		fg1_raw.plot(X,np.array(offical_mean_rank_raw),'b--o',label='offical(243)')
		fg1_raw.legend()

		#fg2_raw.set_title('hit@10')
		fg2_raw.set_xlabel('epoch')
		fg2_raw.set_ylabel('accuracy(%)')
		fg2_raw.plot(X,np.array(hit10),'-r',label='raw hit@10')
		fg2_raw.plot(X,np.array(offical_hit10_raw),'b--o',label='offical(34.9%)')
		fg2_raw.legend()

		plt.tight_layout(pad=1, w_pad=1, h_pad=1)
		plt.savefig('./result_image/raw.png',dpi=80)
		plt.show()
		#2
		plt.figure(figsize=(11, 11),dpi=80)
		f,(fg1_filter,fg2_filter)=plt.subplots(2,1)

		#fg1_filter.set_title('filter mean rank')
		fg1_filter.set_xlabel('epoch')
		fg1_filter.set_ylabel('rank')
		fg1_filter.plot(X,np.array(filter_mean_rank),'-r',label='filter mean rank')
		fg1_filter.plot(X,np.array(offical_mean_rank_filter),'b--o',label='offical(125)')
		fg1_filter.legend()

		#fg2_filter.set_title('filter hit@10')
		fg2_filter.set_xlabel('epoch')
		fg2_filter.set_ylabel('accuracy(%)')
		fg2_filter.plot(X,np.array(filter_hit10),'-r',label='filter hit@10')
		fg2_filter.plot(X,np.array(offical_hit10_filter),'b--o',label='offical(47.1%)')
		fg2_filter.legend()

		plt.tight_layout(pad=1, w_pad=1, h_pad=1)
		plt.savefig('./result_image/filter.png',dpi=80)
		plt.show()

		#3
		plt.figure(figsize=(11, 11),dpi=80)
		f,(fg1_norm,fg2_norm)=plt.subplots(2,1)

		#fg1_norm.set_title('norm mean rank')
		fg1_norm.set_xlabel('epoch')
		fg1_norm.set_ylabel('rank')
		fg1_norm.plot(X,np.array(norm_mean_rank),'-r',label='norm mean rank')
		fg1_norm.plot(X,np.array(offical_mean_rank_raw),'b--o',label='offical raw rank(243)')
		fg1_norm.legend()

		#fg2_norm.set_title('norm hit@10')
		fg2_norm.set_xlabel('epoch')
		fg2_norm.set_ylabel('accuracy(%)')
		fg2_norm.plot(X,np.array(norm_hit10),'-r',label='norm hit@10')
		fg2_norm.plot(X,np.array(offical_hit10_raw),'b--o',label='offical raw hit@10(34.9%)')
		fg2_norm.legend()

		plt.tight_layout(pad=1, w_pad=1, h_pad=1)
		plt.savefig('./result_image/norm.png',dpi=80)
		plt.show()

		#4
		plt.figure(figsize=(11, 11),dpi=80)
		f,(fg1_norm_filter,fg2_norm_filter)=plt.subplots(2,1)

		#fg1_norm_filter.set_title('norm filter mean rank')
		fg1_norm_filter.set_xlabel('epoch')
		fg1_norm_filter.set_ylabel('rank')
		fg1_norm_filter.plot(X,np.array(norm_filter_mean_rank),'-r',label='norm filter mean rank')
		fg1_norm_filter.plot(X,np.array(offical_mean_rank_filter),'b--o',label='offical filter rank(125)')
		fg1_norm_filter.legend()

		#fg2_norm_filter.set_title('norm filter hit@10')
		fg2_norm_filter.set_xlabel('epoch')
		fg2_norm_filter.set_ylabel('accuracy(%)')
		fg2_norm_filter.plot(X,np.array(norm_filter_hit10),'-r',label='norm filter hit@10')
		fg2_norm_filter.plot(X,np.array(offical_hit10_filter),'b--o',label='offical filter hit@10(47.1%)')
		fg2_norm_filter.legend()

		plt.tight_layout(pad=1, w_pad=1, h_pad=1)
		plt.savefig('./result_image/norm_filter.png',dpi=80)
		plt.show()


if __name__ =="__main__":
	main()