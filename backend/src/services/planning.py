"""两类工位、复检工时受限的整批检修排产优化。

每个样本可选免检或一种检修方式；期望损失由完整折外后验与故障/处置损失表计算。
目标：在两类工位剩余工时（整数分钟）约束下，使整批期望损失最小。
模型为双约束多选背包（2-constraint multiple-choice knapsack），用稀疏字典 DP 求全局最优；
同损失时按确定性规则（先比总占用、再按动作顺序 none<quick<deep 的选择序列字典序）打破平局，保证结果可复现。
"""
from ..constants.enums import ACTION_NONE,ACTION_ORDER

def expected_losses(posteriors,loss_map):
    """返回单个样本在各动作下的期望损失 {action_code: loss}。"""
    out={}
    for action in ACTION_ORDER:
        total=0.0
        for label,prob in posteriors.items():
            total+=prob*loss_map[(label,action)]
        out[action]=total
    return out

def optimize(rows,loss_map,action_meta,cap_a,cap_b):
    """rows: [{reference, posteriors:{label:prob}}]
    loss_map: {(fault_label, action_code): 期望损失}
    action_meta: {action_code:(station_key, minutes_per_sample)}，station_key 为 'A'/'B'/None
    cap_a/cap_b: 两类工位剩余分钟（非负整数）
    返回 (selections, stats)。"""
    options=[]
    for r in rows:
        losses=expected_losses(r['posteriors'],loss_map)
        per=[]
        for action in ACTION_ORDER:
            station,minutes=action_meta[action]
            use_a=minutes if station=='A' else 0
            use_b=minutes if station=='B' else 0
            per.append({'action':action,'loss':losses[action],'use_a':use_a,'use_b':use_b})
        options.append(per)
    # 稀疏状态：(used_a, used_b) -> (loss, choice_seq)
    states={(0,0):(0.0,[])}
    for per in options:
        nxt={}
        for (ua,ub),(cur_loss,seq) in states.items():
            for choice,opt in enumerate(per):
                na,nb=ua+opt['use_a'],ub+opt['use_b']
                if na>cap_a or nb>cap_b:continue
                cand=(cur_loss+opt['loss'],seq+[choice])
                old=nxt.get((na,nb))
                if old is None or _prefer(cand,old):
                    nxt[(na,nb)]=cand
        states=nxt
        if not states:raise ValueError('当前剩余工时不足以容纳任何可行排产，请调整人工占用或损失口径')
    # 终局选期望损失最小；平局取总占用更少，再取占用键字典序（确定性）
    best_key=min(states,key=lambda k:(states[k][0],k[0]+k[1],k[0],k[1]))
    best_loss,choices=states[best_key]
    used_a,used_b=best_key
    selections=[];total=0.0
    action_counts={a:0 for a in ACTION_ORDER}
    for i,choice in enumerate(choices):
        opt=options[i][choice];action=opt['action']
        action_counts[action]+=1;total+=opt['loss']
        losses={a:options[i][idx]['loss'] for idx,a in enumerate(ACTION_ORDER)}
        reason=_reason(action,losses,opt['use_a'],opt['use_b'])
        selections.append({'reference':rows[i]['reference'],'action':action,
                           'expected_loss':round(opt['loss'],6),
                           'losses_by_action':{a:round(losses[a],6) for a in ACTION_ORDER},
                           'use_minutes':{'A':opt['use_a'],'B':opt['use_b']},
                           'posteriors':rows[i]['posteriors'],'reason':reason})
    stats={'expected_total_loss':round(total,6),'used_minutes':{'A':used_a,'B':used_b},
           'remaining_minutes':{'A':cap_a-used_a,'B':cap_b-used_b},
           'action_counts':action_counts,'sample_count':len(rows),
           'evaluated_states':len(states)}
    return selections,stats

def _prefer(cand,old):
    """同一容量键下保留哪个部分解：损失低优先；平局保留动作序列字典序更小者（免检优先）。"""
    if cand[0]<old[0]-1e-12:return True
    if cand[0]>old[0]+1e-12:return False
    return cand[1]<old[1]

def _reason(action,losses,use_a,use_b):
    cheapest=min(ACTION_ORDER,key=lambda a:(losses[a],ACTION_ORDER.index(a)))
    minutes=use_a or use_b
    if action==ACTION_NONE:
        if cheapest==ACTION_NONE:return '免检的折后期望损失最低，无需占用工位工时'
        return '低损失检修方式受剩余工时约束不可行，免检为容量内最优选择'
    station='快速复检工位' if use_a else '停机检修工位'
    if action==cheapest:
        return f'该动作折后期望损失最低，占用{station}{minutes}分钟，容量内可行'
    return '理论更优动作受工时容量限制，当前动作为容量约束下的最优可行选择'
