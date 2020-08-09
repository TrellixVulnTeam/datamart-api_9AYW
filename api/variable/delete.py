from db.sql import dal


class VariableDeleter():
    def delete(self, dataset, variable):
        result = dal.query_variable(dataset, variable)
        if not result:
            content = {
                'Error': f'Could not find dataset {dataset} variable {variable}'
            }
            return content, 404

        dal.delete_variable(result['dataset_id'], result['variable_id'], result['property_id'])
        return {"Message": f'Canonical data for Variable: {variable} in Dataset: {dataset} is deleted.'}, 200
