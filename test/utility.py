import os
from requests import put
from requests import post, delete, get


def upload_data_put(file_path, url):
    file_name = os.path.basename(file_path)
    files = {
        'file': (file_name, open(file_path, mode='rb'), 'application/octet-stream')
    }
    return put(url, files=files)


def create_dataset(p_url, return_edges=False, name='Unit Test Dataset', dataset_id='unittestdataset',
                   description='will be deleted in this unit test', url='http://unittest101.org'):
    metadata = {
        'name': name,
        'dataset_id': dataset_id,
        'description': description,
        'url': url
    }
    if return_edges:
        post_url = f'{p_url}/metadata/datasets?tsv=true'
    else:
        post_url = f'{p_url}/metadata/datasets'

    return post(post_url, json=metadata)


def delete_dataset(url, dataset_id='unittestdataset'):
    delete(f'{url}/metadata/datasets/{dataset_id}')
