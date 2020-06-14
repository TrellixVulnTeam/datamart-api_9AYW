import json
import re
import hashlib
import pandas as pd
from flask import request
from db.sql.utils import query_to_dicts
from api.SQLProvider import SQLProvider
from db.sql.kgtk import import_kgtk_dataframe
from .country_wikifier import DatamartCountryWikifier

provider = SQLProvider()
qnode_regex = {}
all_ids_dict = {}
time_precision_dict = {
    'year': '9',
    'month': '10',
    'day': '11',
    'decade': '8',
    'century': '7',
    'millennium': '6',
    'hundred thousand years': '5',
    'million years': '3',
    'billion years': '0'
}


def format_sql_string(values, value_type='str'):
    str = ''
    if value_type == 'str':
        for value in values:
            str += '\'{}\','.format(value)
    elif value_type == 'int':
        for value in values:
            str += '{},'.format(value)
    return str[:-1] if str else None


def create_new_qnodes(dataset_id, values, q_type):
    # q_type can be 'Unit' or 'Source' for now
    # create qnodes for units with this scheme {dataset_id}Unit-{d}
    if q_type == 'Unit':
        _query = "SELECT max(e.node1) as qnode_max FROM edges e WHERE e.label = 'P31' and e.node2 = 'Q47574' and" \
                 " e.node1 like '{}{}-%'".format(dataset_id, q_type)
    else:
        _query = "SELECT max(e.node1) as qnode_max FROM edges e WHERE e.node1 like '{}{}-%'".format(dataset_id, q_type)

    _result = query_to_dicts(_query)[0]
    qnode_max = _result['qnode_max']

    regex_key = '({}{}-)(\d*)'.format(dataset_id, q_type)
    if regex_key not in qnode_regex:
        qnode_regex[regex_key] = re.compile(regex_key)
    _regex = qnode_regex[regex_key]
    if not qnode_max:
        seed = 0
    else:
        u, v = _regex.match(qnode_max).groups()
        seed = int(v) + 1
    _dict = {}
    for value in values:
        _dict[value] = '{}{}-{}'.format(dataset_id, q_type, seed)
        seed += 1
    return _dict


def create_triple(node1, label, node2):
    id_key = '{}-{}'.format(node1, label)
    if id_key not in all_ids_dict:
        all_ids_dict[id_key] = 0
    else:
        all_ids_dict[id_key] += 1
    id_index = all_ids_dict[id_key]
    return {
        'node1': node1,
        'label': label,
        'node2': node2,
        'id': 'Q{}'.format(
            hashlib.sha256(bytes('{}{}{}{}'.format(node1, label, node2, id_index), encoding='utf-8')).hexdigest())
    }


def create_kgtk_measurements(row, dataset_id, variable_id):
    kgtk_measurement_temp = list()
    main_subject = row['main_subject_id'].strip()
    if main_subject:

        main_triple = create_triple(main_subject, variable_id,
                                    '{}{}'.format(row['value'], row['value_unit_id']))
        kgtk_measurement_temp.append(main_triple)

        main_triple_id = main_triple['id']
        kgtk_measurement_temp.append(create_triple(main_triple_id, 'P2006020004', dataset_id))

        kgtk_measurement_temp.append(
            create_triple(main_triple_id, 'P585',
                          '{}/{}'.format('{}{}'.format('^', row['time']),
                                         time_precision_dict[row['time_precision'].lower()])))
        if 'country_id' in row:
            country_id = row['country_id'].strip()
            if country_id:
                kgtk_measurement_temp.append(create_triple(main_triple_id, 'P17', country_id))

        # admin_id = row['admin_id'].strip()
        # if admin_id:
        #     kgtk_measurement_temp.append(create_triple(main_triple_id, 'P131', admin_id))
        #
        # place_id = row['place_id'].strip()
        # if place_id:
        #     kgtk_measurement_temp.append(create_triple(main_triple_id, 'P276', place_id))

        source_id = row['source_id'].strip()
        if source_id:
            kgtk_measurement_temp.append(create_triple(main_triple_id, 'P248', source_id))

    return kgtk_measurement_temp


def canonical_data(dataset, variable):
    # check if the dataset exists

    dataset_id = provider.get_dataset_id(dataset)

    if not dataset_id:
        return {'Error': 'Dataset not found: {}'.format(dataset)}, 404

    # check if variable exists for the dataset
    # P2006020003 - Variable Measured
    # P1687 - Corresponds to property

    variable_query = f"""Select e.node1, e.node2 from edges e where e.node1 in (
                            select e_variable.node1 from edges e_variable
                                    where e_variable.node1 in
                                (
                                    select e_dataset.node2 from edges e_dataset
                                    where e_dataset.node1 = '{dataset_id}'
                                    and e_dataset.label = 'P2006020003'
                                )
                                and e_variable.label = 'P1813' and e_variable.node2 = '{variable}'
                            )
                            and e.label = 'P1687'
                                """

    variable_result = query_to_dicts(variable_query)
    if len(variable_result) == 0:
        return {'error': 'Variable: {} not found for the dataset: {}'.format(variable, dataset)}, 404

    variable_pnode = variable_result[0]['node2']

    # dataset and variable has been found, wikify and upload the data
    df = pd.read_csv(request.files['file'], dtype=object, lineterminator='\r')
    d_columns = list(df.columns)
    country_wikifier = DatamartCountryWikifier()
    df_wikified = country_wikifier.wikify(df, 'main_subject', output_col_name="main_subject_id")
    if 'country' in d_columns:
        df_wikified = country_wikifier.wikify(df_wikified, 'country', output_col_name="country_id")
    units = list(df_wikified['value_unit'].unique())

    units_query = "SELECT e.node1, e.node2 FROM edges e WHERE e.node2 in ({}) and e.label = 'label'".format(
        format_sql_string(units))

    units_results = query_to_dicts(units_query)

    unit_qnode_dict = {}

    for ur in units_results:
        unit_qnode_dict[ur['node2']] = ur['node1']

    no_qnode_units = list()
    no_qnode_units.extend([u for u in units if u not in unit_qnode_dict])

    no_unit_qnode_dict = create_new_qnodes(dataset_id, no_qnode_units, 'Unit')

    df_wikified['value_unit_id'] = df_wikified['value_unit'].map(
        lambda x: unit_qnode_dict[x] if x in unit_qnode_dict else no_unit_qnode_dict[x])

    sources = list(df_wikified['source'].unique())

    sources_query = "SELECT  e.node1, e.node2 FROM edges e WHERE e.label = 'label' and e.node2 in  ({})".format(
        format_sql_string(sources))

    sources_results = query_to_dicts(sources_query)

    source_qnode_dict = {}
    for sr in sources_results:
        source_qnode_dict[sr['node2']] = sr['node1']

    no_qnode_sources = list()
    no_qnode_sources.extend([s for s in sources if s not in source_qnode_dict])

    no_source_qnode_dict = create_new_qnodes(dataset_id, no_qnode_sources, 'Source')

    df_wikified['source_id'] = df_wikified['source'].map(
        lambda x: source_qnode_dict[x] if x in source_qnode_dict else no_source_qnode_dict[x])

    kgtk_format_list = list()
    for i, row in df_wikified.iterrows():
        kgtk_format_list.extend(create_kgtk_measurements(row, dataset_id, variable_pnode))

    # create rows for new created variables Unit Qnodes and Source Qnodes
    for k in no_unit_qnode_dict:
        _q = no_unit_qnode_dict[k]
        kgtk_format_list.append(create_triple(_q, 'label', json.dumps(k)))
        kgtk_format_list.append(create_triple(_q, 'P31', 'Q47574'))  # unit of measurement

    for k in no_source_qnode_dict:
        kgtk_format_list.append(create_triple(no_source_qnode_dict[k], 'label', json.dumps(k)))

    df_kgtk = pd.DataFrame(kgtk_format_list)
    import_kgtk_dataframe(df_kgtk)

    return '{} rows imported!'.format(len(df)), 201  # original file
