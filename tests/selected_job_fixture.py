"""Краткие функциональные fixtures приватного selected-files договора."""
def native_manifest(project):
    project.setdefault('exerciseId',project['qualifiedId'].split('/')[-1])
    project.setdefault('source','labs/fixture.qmd')
    project.setdefault('verificationTests',[])
    project.setdefault('contractFixtures',[])
    project.setdefault('readiness',{'ready':True,'missing':[]})
    project.setdefault('references',[])
    for ref in project['references']:
        declaration=next(r for r in project['check'].get('references',[]) if r['name']==ref['name'])
        ref.setdefault('root',declaration['root']);ref.setdefault('optional',declaration.get('optional',False));ref.setdefault('available',True);ref.setdefault('group',ref['name']);ref.setdefault('targets',[r['target'] for r in ref['sources']])
    return {'schemaVersion':3,'courseId':project['qualifiedId'].split('/')[0],'bookRoot':'tasks','projects':[project]}
