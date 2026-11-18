from enum import Enum
class Role(str,Enum):
    admin='admin'; analyst='analyst'; viewer='viewer'
class RunState(str,Enum):
    queued='queued'; running='running'; completed='completed'; failed='failed'
class ReviewState(str,Enum):
    draft='draft'; approved='approved'
class PlanState(str,Enum):
    computing='computing'; ready='ready'; confirmed='confirmed'; executed='executed'; cancelled='cancelled'; failed='failed'
# 处置动作：免检不占工时；快速复检与停机检修分别占用两类工位
ACTION_NONE='none'; ACTION_QUICK='quick'; ACTION_DEEP='deep'
ACTION_ORDER=(ACTION_NONE,ACTION_QUICK,ACTION_DEEP)
