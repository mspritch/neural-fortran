import h5py
import json
import warnings
import argparse
import numpy as np

import numpy as np
import math
import keras
from keras.models import Sequential, Model
from keras.layers import Dense, Dropout, BatchNormalization
from keras.layers import Input, Activation
from keras import optimizers

INPUT = ['input']
ACTIVATIONS = ['relu', 'linear', 'leakyrelu']
SUPPORTED_LAYERS = ['dense', 'dropout', 'batchnormalization'] + ACTIVATIONS + INPUT

def txt_to_h5(weights_file_name, output_file_name=''):
    '''
    Convert a txt file to Keras h5 file

    REQUIRED:
        weights_file_name (str): path to a txt file used by neural fortran
    OPTIONAL:
        output_file_name  (str): desired output path for the produced h5 file
    '''

    # TODO:
    # parse txt file following convention in
    #       https://github.com/jordanott/neural-fortran/blob/development/KerasWeightsProcessing/README.md
    # create keras model with each of desired layers
    # manually load:
    #       - weights
    #       - biases
    #       - batchnorm params
    #           - see order of those params in README
    #

    bias             = []                                       # dense layer
    weights          = []                                       # dense layer
    batchnorm_params = []                                       # batchnormalization layers

    bias_count       = 0
    weights_count    = 0
    batchnorm_count  = 0

    with open(weights_file_name, mode='r') as weights_file:
        lines = weights_file.readlines()

        for idx, line in enumerate(lines):

            if idx == 0:
                num_layers = int(line)
                continue

            line = line.strip().split("\t")
            layer_type = line[0]

            if layer_type in SUPPORTED_LAYERS:
                param = line[1]
                if layer_type == 'input':
                    input = Input(shape=(int(param),), name = "input")
                    x     = input

                elif layer_type == 'dense':
                    bias_count += 1; weights_count += 1
                    x = Dense(int(param),name = "dense_{}".format(weights_count))(x)

                elif layer_type == 'dropout':
                    x = Dropout(float(param))(x)

                elif layer_type == 'relu':
                    x = Activation('relu')(x)

                elif layer_type == 'relu':
                    x = Activation('relu',alpha=float(param))(x)

                elif layer_type == 'batchnormalization':
                    batchnorm_count+=4
                    x = BatchNormalization(name = 'batch_normalization_{}'.format(batchnorm_count))(x)

                elif layer_type == 'linear':
                    x = Activation('linear')(x)

            elif not layer_type.isalpha():
                # found bias or weights numbers
                w = np.asarray([float(num) for num in line])

                if bias_count > 0:
                    bias_count -= 1
                    bias.append(w)

                elif weights_count > 0:
                    weights_count -= 1
                    weights.append(w)

                elif batchnorm_count > 0:
                    batchnorm_count -= 1
                    batchnorm_params.append(w)

    # create model
    model = Model(inputs=input, outputs=x)


    # compile model
    model.compile(loss='mse',
                  optimizer='sgd',
                  metrics=['accuracy'])


    # set weights and biases
    for idx, w in enumerate(weights):
        name    = 'dense_{}'.format(idx+1)
        layer   = model.get_layer(name)
        w       = w.reshape(layer.output_shape[1],layer.input_shape[1]).T
        layer.set_weights( [w, bias[idx]] )

    # set batchnorm parameters
    for idx in range(0,len(batchnorm_params),4):
        params  = batchnorm_params[idx:idx+4]
        name    = 'batch_normalization_{}'.format(idx // 4 + 1)
        layer   = model.get_layer(name)
        layer.set_weights( params )

    # view summary

    if not output_file_name:
        # if not specified will use path of weights_file with h5 extension
        output_file_name = weights_file_name.replace('.txt', '_converted.h5')

    model.save(output_file_name)



def h5_to_txt(weights_file_name, output_file_name=''):
    '''
    Convert a Keras h5 file to a txt file

    REQUIRED:
        weights_file_name (str): path to a Keras h5 file
    OPTIONAL:
        output_file_name  (str): desired path for the produced txt file
    '''

    info_str         = '{name}\t{info}\n'                       # to store in layer info; config of network
    bias             = []                                       # dense layer
    weights          = []                                       # dense layer
    layer_info       = []                                       # all layers
    batchnorm_params = []                                       # batchnormalization layers

    #check and open file
    with h5py.File(weights_file_name,'r') as weights_file:

        # weights of model
        model_weights = weights_file['model_weights']
        keras_version = weights_file.attrs['keras_version']

        # Decode using the utf-8 encoding; change values for eval
        model_config = weights_file.attrs['model_config'].decode('utf-8')
        model_config = model_config.replace('true','True')
        model_config = model_config.replace('false','False')
        model_config = model_config.replace('null','None')
        # convert to dictionary
        model_config = eval(model_config)

        # store first dimension for the input layer
        layer_info.append(
            info_str.format(
                name = 'input',
                info = model_config['config']['layers'][0]['config']['batch_input_shape'][1]
            )
        )

        # check what type of keras model sequential or functional
        if model_config['class_name'] == 'Model':
            layer_config = model_config['config']['layers'][1:]
        else:
            layer_config = model_config['config']['layers']

        for idx,layer in enumerate(layer_config):
            name = layer['config']['name']
            class_name = layer['class_name'].lower()

            if class_name not in SUPPORTED_LAYERS:
                warnings.warn('Unsupported layer found! Skipping...')
                continue
            elif class_name == 'dense':
                # get weights and biases out of dictionary
                layer_bias    = np.array(
                    model_weights[name][name]['bias:0']
                )
                layer_weights = np.array(
                    model_weights[name][name]['kernel:0']
                )

                # store bias values
                bias.append(layer_bias)
                # store weight value
                weights.append(layer_weights)

                activation = layer['config']['activation']

                if activation not in ACTIVATIONS:
                    warnings.warn('Unsupported activation found! Replacing with Linear.')
                    activation = 'linear'

                # store dimension of hidden dim
                layer_info.append(
                    info_str.format(
                        name = class_name,
                        info = layer_weights.shape[1]
                    )
                )
                # add information about the activation
                layer_info.append(
                    info_str.format(
                        name = activation,
                        info = 0
                    )
                )
            elif class_name == 'batchnormalization':
                # get beta, gamma, moving_mean, moving_variance from dictionary
                for key in sorted(model_weights[name][name].keys()):
                    # store batchnorm params
                    batchnorm_params.append(
                        np.array(
                            model_weights[name][name][key]
                        )
                    )

                # store batchnorm layer info
                layer_info.append(
                    info_str.format(
                        name = class_name,
                        info = 0
                    )
                )

            elif class_name == 'dropout':
                layer_info.append(
                    info_str.format(
                        name = class_name,
                        info = layer['config']['rate']
                    )
                )

            elif class_name in ACTIVATIONS:
                # replace previous dense layer with the advanced activation function (LeakyReLU)
                layer_info[-1] = info_str.format(
                    name = class_name,
                    info = layer['config']['alpha']
                )

    if not output_file_name:
        # if not specified will use path of weights_file with txt extension
        output_file_name = weights_file_name.replace('.h5', '.txt')

    with open(output_file_name,"w") as output_file:
        output_file.write(str(len(layer_info)) + '\n')

        output_file.write(
            ''.join(layer_info)
        )

        for b in bias:
            bias_str = '\t'.join(
                '{:0.7e}'.format(num) for num in b.tolist()
            )
            output_file.write(bias_str + '\n')

        for w in weights:
            weights_str = '\t'.join(
                '{:0.7e}'.format(num) for num in w.T.flatten()
            )
            output_file.write(weights_str + '\n')

        for b in batchnorm_params:
            param_str = '\t'.join(
                '{:0.7e}'.format(num) for num in b.tolist()
            )
            output_file.write(param_str + '\n')


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--weights_file", type=str, help='path to desired file to be processed')
    parser.add_argument('--output_file', default='', type=str)
    args =  parser.parse_args()

    if args.weights_file.endswith('.h5'):
        h5_to_txt(
            weights_file_name=args.weights_file,
            output_file_name=args.output_file
        )
    elif args.weights_file.endswith('.txt'):
        txt_to_h5(
            weights_file_name=args.weights_file,
            output_file_name=args.output_file
        )

    else:
        warnings.warn('Unsupported file extension')
