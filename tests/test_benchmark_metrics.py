from tools.benchmark_references import summarize


def measurement(contacts):
    return {'contacts':contacts,'bends':2,'length':100,'sequence_contacts':contacts,'sequence_bends':2,'sequence_length':100,'extent_area':1000,'features':{'straight_fraction':.5,'forward_hop_excess':0,'parallel_crowding_per_flow':0,'hotspot_excess':0}}


def test_paired_summary_exposes_lost_success_and_zero_baseline_regressions():
    results=[{'id':'a','engine':'old','status':'success','measurements':measurement(0)},
             {'id':'a','engine':'new','status':'success','measurements':measurement(1)},
             {'id':'b','engine':'old','status':'success','measurements':measurement(0)},
             {'id':'b','engine':'new','status':'failed'}]
    r=summarize(results,'old','new')
    assert r['paired_success_count']==1 and r['lost_successes']==['b']
    assert r['regressions']['contacts']==['a']
    assert r['totals']['contacts']['change_percent'] is None
