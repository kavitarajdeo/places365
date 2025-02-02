# PlacesCNN to predict the scene category, attribute, and class activation map in a single pass
# by Bolei Zhou, sep 2, 2017

import torch
from torch.autograd import Variable as V
import torchvision.models as models
from torchvision import transforms as trn
from torch.nn import functional as F
import os
import numpy as np
from skimage import data, color
from skimage.transform import rescale, resize, downscale_local_mean
import cv2
from PIL import Image
from google.colab.patches import cv2_imshow
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from google.colab import auth
from oauth2client.client import GoogleCredentials

# 1. Authenticate and create the PyDrive client.
auth.authenticate_user()
gauth = GoogleAuth()
gauth.credentials = GoogleCredentials.get_application_default()
drive = GoogleDrive(gauth)

def load_labels():
    # prepare all the labels
    # scene category relevant
    file_name_category = 'categories_places365.txt'
    if not os.access(file_name_category, os.W_OK):
        synset_url = 'https://raw.githubusercontent.com/csailvision/places365/master/categories_places365.txt'
        os.system('wget ' + synset_url)
    classes = list()
    with open(file_name_category) as class_file:
        for line in class_file:
            classes.append(line.strip().split(' ')[0][3:])
    classes = tuple(classes)

    # indoor and outdoor relevant
    file_name_IO = 'IO_places365.txt'
    if not os.access(file_name_IO, os.W_OK):
        synset_url = 'https://raw.githubusercontent.com/csailvision/places365/master/IO_places365.txt'
        os.system('wget ' + synset_url)
    with open(file_name_IO) as f:
        lines = f.readlines()
        labels_IO = []
        for line in lines:
            items = line.rstrip().split()
            labels_IO.append(int(items[-1]) -1) # 0 is indoor, 1 is outdoor
    labels_IO = np.array(labels_IO)

    # scene attribute relevant
    file_name_attribute = 'labels_sunattribute.txt'
    if not os.access(file_name_attribute, os.W_OK):
        synset_url = 'https://raw.githubusercontent.com/csailvision/places365/master/labels_sunattribute.txt'
        os.system('wget ' + synset_url)
    with open(file_name_attribute) as f:
        lines = f.readlines()
        labels_attribute = [item.rstrip() for item in lines]
    file_name_W = 'W_sceneattribute_wideresnet18.npy'
    if not os.access(file_name_W, os.W_OK):
        synset_url = 'http://places2.csail.mit.edu/models_places365/W_sceneattribute_wideresnet18.npy'
        os.system('wget ' + synset_url)
    W_attribute = np.load(file_name_W)

    return classes, labels_IO, labels_attribute, W_attribute

def hook_feature(module, input, output):
    features_blobs.append(np.squeeze(output.data.cpu().numpy()))

def returnCAM(feature_conv, weight_softmax, class_idx):
    # generate the class activation maps upsample to 256x256
    size_upsample = (256, 256)
    nc, h, w = feature_conv.shape
    output_cam = []
    for idx in class_idx:
        cam = weight_softmax[class_idx].dot(feature_conv.reshape((nc, h*w)))
        cam = cam.reshape(h, w)
        cam = cam - np.min(cam)
        cam_img = cam / np.max(cam)
        cam_img = np.uint8(255 * cam_img)
        #output_cam.append(imresize(cam_img, size_upsample))
        output_cam = np.array(Image.fromarray(cam_img).resize(size=size_upsample))
        #output_cam = resize(cam_img,(cam_img.shape[0] // 4,cam_img.shape[1] // 4),
         #                   anti_aliasing=True)
    return output_cam

def returnTF():
# load the image transformer
    tf = trn.Compose([
        trn.Resize((224,224)),
        trn.ToTensor(),
        trn.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])
    return tf


def load_model():
    # this model has a last conv feature map as 14x14

    model_file = 'wideresnet18_places365.pth.tar'
    if not os.access(model_file, os.W_OK):
        os.system('wget http://places2.csail.mit.edu/models_places365/' + model_file)
        os.system('wget https://raw.githubusercontent.com/csailvision/places365/master/wideresnet.py')

    import wideresnet
    model = wideresnet.resnet18(num_classes=365)
    checkpoint = torch.load(model_file, map_location=lambda storage, loc: storage)
    state_dict = {str.replace(k,'module.',''): v for k,v in checkpoint['state_dict'].items()}
    model.load_state_dict(state_dict)
    model.eval()



    # the following is deprecated, everything is migrated to python36

    ## if you encounter the UnicodeDecodeError when use python3 to load the model, add the following line will fix it. Thanks to @soravux
    #from functools import partial
    #import pickle
    #pickle.load = partial(pickle.load, encoding="latin1")
    #pickle.Unpickler = partial(pickle.Unpickler, encoding="latin1")
    #model = torch.load(model_file, map_location=lambda storage, loc: storage, pickle_module=pickle)

    model.eval()
    # hook the feature extractor
    features_names = ['layer4','avgpool'] # this is the last conv layer of the resnet
    for name in features_names:
        model._modules.get(name).register_forward_hook(hook_feature)
    return model


# load the labels
classes, labels_IO, labels_attribute, W_attribute = load_labels()

# load the model
features_blobs = []
model = load_model()

# load the transformer
tf = returnTF() # image transformer

# get the softmax weight
params = list(model.parameters())
weight_softmax = params[-2].data.numpy()
weight_softmax[weight_softmax<0] = 0

import pathlib
# load the test image
def load_image():
    #img_url = 'C:\\Users\\Kavita\\data-science\\places365_modified\\data\\images.jpg'
    img_url = 'places365/data/images.jpg'
    img_file = pathlib.Path(img_url)
    img = Image.open(img_url)
    img_np = cv2.imread(img_url)
#    if not img.exists():
#        img_url = 'http://places.csail.mit.edu/demo/6.jpg'
#        os.system('wget %s -q -O test.jpg' % img_url)
#        img = Image.open('test.jpg')
    input_img = V(tf(img).unsqueeze(0))
    return input_img,img_url,img_np

def convert_video_frames():
    vid_url = '1HVY2rbbTWUeZiYRtN41EMIIZMxXQ5TRr'
    if not os.access(vid_url, os.W_OK):
        #vid_url = "https://drive.google.com/open?id=1-ECPBt94prpnaJnkS6XBDip_Yx2A1a0Q"
        #os.system('wget '+vid_url)
        vid_file = drive.CreateFile({'id': '1HVY2rbbTWUeZiYRtN41EMIIZMxXQ5TRr'})
        vid_file.GetContentFile('/content/video002.mp4')
    #vid_file = np.load(vid_url)

    vidcap = cv2.VideoCapture("/content/video002.mp4")
    if not os.path.exists("/content/video_frame"): 
        os.makedirs('video_frame')
    #frame
    #print("vid_url"+vid_url)
    currentframe = 1
    second = 0
    framerate = 0.5
    
    def getFrame(sec):
        print("In getFrame")
        vidcap.set(cv2.CAP_PROP_POS_MSEC,sec*1000)
        print("before vidcap.read")
        hasFrame,image = vidcap.read()
        print("after vidcap.read - hasFrame:"+ str(hasFrame))
        if hasFrame:
            name = './video_frame/'+str(currentframe)+'.jpg'
            print('Creating..'+name)
            #writing the extracted images
            cv2.imwrite(name,image)
            image = Image.fromarray(image)
            #image = Image.open(image)
            image = V(tf(image).unsqueeze(0))

            logit = model.forward(image)
            h_x = F.softmax(logit, 1).data.squeeze()
            probs, idx = h_x.sort(0, True)
            probs = probs.numpy()
            idx = idx.numpy()

            #print('RESULT ON :-' + img_url)
            # output the IO prediction
            io_image = np.mean(labels_IO[idx[:10]]) # vote for the indoor or outdoor
            if io_image < 0.5:
                print('--TYPE OF ENVIRONMENT: indoor')
            else:
                print('--TYPE OF ENVIRONMENT: outdoor')

            # output the prediction of scene category
            print('--SCENE CATEGORIES:')
            for i in range(0, 5):
                print('{:.3f} -> {}'.format(probs[i], classes[idx[i]]))

            # output the scene attributes
            responses_attribute = W_attribute.dot(features_blobs[1])
            idx_a = np.argsort(responses_attribute)
            print('--SCENE ATTRIBUTES:')
            print(', '.join([labels_attribute[idx_a[i]] for i in range(-1,-10,-1)]))


            # generate class activation mapping
            print('Class activation map is saved as cam.jpg')
            CAMs = returnCAM(features_blobs[0], weight_softmax, [idx[0]])

            # render the CAM and output
            #img = cv2.imread('test.jpg')
            #img = cv2.imread(input_img)
            height, width, _ = img_np.shape
            heatmap = cv2.applyColorMap(cv2.resize(CAMs[0],(width, height)), cv2.COLORMAP_JET)
            result = heatmap * 0.4 + img_np * 0.5
            cv2.imwrite('cam'+str(currentframe)+'.jpg', result)     
        return hasFrame
    success = True
    while success or currentframe <15000: 
        currentframe += 1
        second = second+ framerate
        second = round(second/2)
        success = getFrame(second)
    #vid_url.release()
    #cv2.destroyAllWindows()
    

# forward pass
input_img,img_url,img_np = load_image()
convert_video_frames()
logit = model.forward(input_img)
h_x = F.softmax(logit, 1).data.squeeze()
probs, idx = h_x.sort(0, True)
probs = probs.numpy()
idx = idx.numpy()

print('RESULT ON :-' + img_url)
# output the IO prediction
io_image = np.mean(labels_IO[idx[:10]]) # vote for the indoor or outdoor
if io_image < 0.5:
    print('--TYPE OF ENVIRONMENT: indoor')
else:
    print('--TYPE OF ENVIRONMENT: outdoor')

# output the prediction of scene category
print('--SCENE CATEGORIES:')
for i in range(0, 5):
    print('{:.3f} -> {}'.format(probs[i], classes[idx[i]]))

# output the scene attributes
responses_attribute = W_attribute.dot(features_blobs[1])
idx_a = np.argsort(responses_attribute)
print('--SCENE ATTRIBUTES:')
print(', '.join([labels_attribute[idx_a[i]] for i in range(-1,-10,-1)]))


# generate class activation mapping
print('Class activation map is saved as cam.jpg')
CAMs = returnCAM(features_blobs[0], weight_softmax, [idx[0]])

# render the CAM and output
#img = cv2.imread('test.jpg')
#img = cv2.imread(input_img)
height, width, _ = img_np.shape
heatmap = cv2.applyColorMap(cv2.resize(CAMs[0],(width, height)), cv2.COLORMAP_JET)
result = heatmap * 0.4 + img_np * 0.5
cv2.imwrite('cam.jpg', result)
#cv2_imshow('cam.jpg')

#convert processed images to a video
