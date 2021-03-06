"""Modules file, each module, defined as a function,
    is a part of the model.

    @author: Zeyu Li <zyli@cs.ucla.edu> or <zeyuli@g.ucla.edu>

    tf.version: 1.14.0
"""

import tensorflow as tf
from utils import get_activation_func


def autoencoder(var_scope, input_features, layers, regularizer=None, initializer=None):
    """Auto encoder for structural context of users 

    Args:
        var_scope - variable scope of the ops within the function
        input_features - raw input structural context
        layers - the layers of enc and dec. [hid1_dim, ..., hidk_dim, out_dim]
        regularizer -
        initializer -

    Returns:
        output_feature - the output features
        recon_loss - reconstruction loss
    """

    with tf.compat.v1.variable_scope(var_scope):
        features = input_features

        # encoder
        for i in range(len(layers)):
            features = tf.compat.v1.layers.dense(inputs=features,
                units=layers[i], activation=tf.nn.relu, use_bias=True,
                kernel_regularizer=regularizer, kernel_initializer=initializer,
                bias_regularizer=regularizer, name="usc_enc_{}".format(i))

        # encoded hidden representation
        hidden_feature = features  # (b, rep_dim)

        return hidden_feature, tf.constant(0., dtype=tf.float32)


def attentional_fm(var_scope, input_features, emb_dim, hid_rep_dim, feat_size, attr_size,
                   is_training, use_dropout, dropout_rate,
                   initializer=None, regularizer=None):
    """attentional factorization machine for attribute feature extractions

    Shapes:
        b - batch_size
        k - number of fields
        d - embedding_size
        h - hidden representation dimension
        |A| - total number of attributes

    Args:
        var_scope - [str]
        input_features - [int] (b, k) input discrete features
        emb_dim - [int] dimension of each embedding, d
        hid_rep_dim - [int] hidden representation dimension 
        feat_size - [int] total number of distinct features (fields) for FM, A
        attr_size - [int] total number of fields , abbrev. k
        is_training - [tf.placeholder bool] the placeholder indicating whether traing/test
        use_dropout - [bool] whether to use dropout in AFM
        dropout_rate - [float] the ratio of dropout (only when `use_dropout`=True)

    Returns:
        afm - attentional factorization machine output
        attn_out - attention output 

    """

    with tf.compat.v1.variable_scope(var_scope) as scope:
        embedding_mat = get_embeddings(vocab_size=feat_size, num_units=emb_dim,
            var_scope=scope, zero_pad=True)  # (|A|+1, d) lookup table for all attr emb
        uattr_emb = tf.nn.embedding_lookup(embedding_mat, input_features)  # (b, k, d)

        attn_b = tf.compat.v1.get_variable(name="attention_b1", dtype=tf.float32,
            shape=[emb_dim], initializer=initializer, regularizer=regularizer)  # (d)

        # FIRST ORDER
        attn_q1 = tf.compat.v1.get_variable(name="attention_q1", dtype=tf.float32,
            shape=[emb_dim, 1], initializer=initializer, regularizer=regularizer)  # (d, 1)
        beta_logits = tf.nn.relu(tf.matmul(uattr_emb, attn_q1))  # (b, k, 1)
        attn_out1_weights = tf.nn.softmax(beta_logits, axis=1)  # (b, k, 1)

        afm1 = tf.reduce_sum(tf.multiply(attn_out1_weights, uattr_emb),  # (b,k,d)
                             axis=1)  # (b,d)
        attn_out1 = tf.squeeze(attn_out1_weights)  # (b,k)

        print(afm1.shape)

        # SECOND ORDER
        element_wise_prod_list = []

        attn_W = tf.compat.v1.get_variable(name="attention_W", dtype=tf.float32,
            shape=[emb_dim, hid_rep_dim], initializer=initializer, 
            regularizer=regularizer)
        attn_q2 = tf.compat.v1.get_variable(name="attention_q2", dtype=tf.float32,
            shape=[hid_rep_dim], initializer=initializer, regularizer=regularizer)
        attn_b2 = tf.compat.v1.get_variable(name="attention_b", dtype=tf.float32,
            shape=[hid_rep_dim], initializer=initializer, regularizer=regularizer)

        for i in range(0, attr_size):
            for j in range(i+1, attr_size):
                element_wise_prod_list.append(
                    tf.multiply(uattr_emb[:, i, :], uattr_emb[:, j, :]))

        element_wise_prod = tf.stack(element_wise_prod_list, axis=1)  # (b,(k*(k-1)/2,d)
        num_interactions = attr_size * (attr_size - 1) // 2  # aka: k *(k-1)/2

        # attentional part
        attn_mul = tf.reshape(
            tf.matmul(tf.reshape(
                element_wise_prod, shape=[-1, emb_dim]), attn_W),
            shape=[-1, num_interactions, hid_rep_dim])  # b * (k*k-1)/2) * h

        attn_relu = tf.reduce_sum(
            tf.multiply(attn_q2, tf.nn.relu(attn_mul + attn_b2)), axis=2, keepdims=True)
        # after relu/multiply: b*(k*(k-1)/2)*h;
        # after reduce_sum + keepdims: b*(k*(k-1)/2)*1

        attn_out2 = tf.nn.softmax(attn_relu, axis=1)  # b*(k*(k-1)*1
        test = attn_out2

        # just added relu Jan30
        afm2 = tf.reduce_sum(
            tf.multiply(attn_out2, element_wise_prod), axis=1, name="afm")
        # afm2: b*(k*(k-1))*d => b*d

        attn_out2 = tf.squeeze(attn_out2, name="attention_output")

        afm = tf.nn.bias_add(afm1 + afm2, attn_b)  # (b*d)
        afm = tf.layers.dense(afm, hid_rep_dim, activation=tf.nn.relu,
                              use_bias=False)  # (b*h)

        if use_dropout:
            print(use_dropout, dropout_rate)
            afm = tf.layers.dropout(afm, dropout_rate, training=is_training)

        return afm, attn_out1, attn_out2, test


def gatnet(var_scope, embedding_mat, adj_mat, input_indices, hid_rep_dim,
           is_training, n_heads, ft_drop=0.0, attn_drop=0.0):
    """Graph Attention Network component for users/items

    Code adapted from: https://github.com/PetarV-/GAT
    But only implemented a simple (one-layered) version

    Notations:
        b - batch size
        n - total number of nodes (user-friendship graph)
        k - internal representation size
        d - embedding size of 

    Args:
        var_scope - variable scope
        embedding_mat - [float32] (n, d) the whole embedding matrix of nodes
        adj_mat - [int] (b, n) adjacency matrix for the batch
        input_indices - [int] (b, 1) the inputs of batch user indices
        hid_rep_dim - [int] internal representation dimension
        is_training - [tf.placeholder bool] the placeholder indicating whether traing/test
        n_heads - [int] number of heads
        ft_drop - feature dropout 
        attn_drop - attentional weight dropout (a.k.a., coef_drop)

    Notes:
        1. How to get bias_mat from adj_mat (learned from GAT repo issues)?
            - adj_mat, bool or int of (0, 1)
            - adj_mat, cast to float32
            - 1 - adj_mat, 0 => 1 and 1 => 0
            - -1e9 * (above): 0 => -1e9 and 1 => 0
            - obtained bias_mat
    """

    with tf.compat.v1.variable_scope(var_scope):

        bias_mat = -1e9 * (1 - tf.cast(adj_mat, dtype=tf.float32))  # (b, d)
        hidden_features = []
        attns = []

        for i in range(n_heads):
            # (b, oz), (b, n)
            hid_feature, attn = gat_attn_head(
                input_indices=input_indices, emb_lookup=embedding_mat, bias_mat=bias_mat,
                output_size=hid_rep_dim, activation=tf.nn.relu, ft_drop=ft_drop,
                coef_drop=attn_drop, is_training=is_training, head_id=i)
            hidden_features.append(hid_feature)
            attns.append(attn)

        h_1 = tf.concat(hidden_features, axis=-1)  # [n_head*(b, oz)] => (b, oz*n_head)
        logits = tf.layers.dense(h_1, hid_rep_dim, use_bias=False,
                                 activation=tf.nn.relu)

        return logits,  attns


def gat_attn_head(input_indices, emb_lookup, output_size, bias_mat, activation,
                  is_training, head_id, ft_drop=0.0, coef_drop=0.0):
    """Single graph attention head

    Notes:
        1. removed the residual for the purpose of simplicity

    Notations:
        b - batch size
        n - total node size
        d - the dimension of embeddings
        k - feature size (embedding/representation size)
        oz - output size

    Args:
        input_indices - [int] (b) input indices of batch user
        emb_lookup - [float] (n, d) the lookup table of embedings
        output_size - (oz) output size (internal representation size)
        bias_mat - (b, n) bias (or mask) matrix (0 for edges, 1e-9 for non-edges)
        activation - activation function
        is_training - same as above
        head_id - the 
        ft_drop - feature dropout rate, a.k.a., feed-forward dropout
            (e.g., 0.2 => 20% units would be dropped)
        coef_drop - coefficent dropput rate

    Returns:
        ret - (b, oz) weighted (attentional) aggregated features for each node
        coefs - (b, n) the attention distribution
    """

    with tf.compat.v1.variable_scope("gat_attn_head_{}".format(head_id)):
        if ft_drop != 0.0:
            emb_lookup = tf.compat.v1.layers.dropout(
                emb_lookup, ft_drop, training=is_training)

        # W*(whole-emb_mat), h->Wh, from R^f to R^F', (n, oz)
        hid_emb_lookup = tf.compat.v1.layers.dense(emb_lookup, output_size, use_bias=False)

        # the batch of Wh's of the users, (b, oz)
        b_hid_emb = tf.nn.embedding_lookup(hid_emb_lookup, input_indices)

        # simplest self-attention possible, concatenation implementiation
        f_1 = tf.layers.dense(b_hid_emb, 1)  # (b, 1)
        f_2 = tf.layers.dense(hid_emb_lookup, 1)  # (n, 1)
        logits = f_1 + tf.transpose(f_2)  # (b, n)
        coefs = tf.nn.softmax(tf.nn.leaky_relu(logits) + bias_mat)  # (b, n)

        if coef_drop != 0.0:
            coefs = tf.layers.dropout(coefs, coef_drop, training=is_training)

        if ft_drop != 0.0:
            hid_emb_lookup = tf.layers.dropout(
                hid_emb_lookup, ft_drop, training=is_training)

        # coefs are masked
        vals = tf.matmul(coefs, hid_emb_lookup)  # (b, oz)
        ret = activation(tf.contrib.layers.bias_add(vals))  # (b, oz)

        return ret, coefs


def get_embeddings(var_scope, vocab_size, num_units, zero_pad=False):
    """Construct a embedding matrix

    Args:
        var_scope - the variable scope of the matrix
        vocab_size - vocabulary size (the V.)
        num_units - the embedding size (the d.)
        zero_pad - [bool] whether to pad the matrix by column of zeros

    Returns:
        embedding matrix - [float] (V+1, d)
    """

    with tf.compat.v1.variable_scope(var_scope, reuse=tf.compat.v1.AUTO_REUSE):
        embeddings = tf.compat.v1.get_variable('embedding_matrix',
            dtype=tf.float32, shape=[vocab_size, num_units],
            initializer=tf.contrib.layers.xavier_initializer())
        if zero_pad:
            embeddings = tf.concat((tf.zeros(shape=[1, num_units]),
                embeddings[1:, :]), 0)
        return embeddings
