# Copyright (c) 2013 The SAYCBridge Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from builtins import object
from z3b import enum
from z3b.constraints import *
from z3b.model import *
from z3b.natural import *
from z3b.preconditions import *
from z3b.rule_compiler import Rule, RuleCompiler, all_priorities_for_rule, rule_order, categories


def lower_calls_first(call_names):
    priorities = enum.Enum(*call_names)
    rule_order.order(*reversed(priorities))
    return copy_dict(priorities, call_names)


relay_priorities = enum.Enum(
    "SuperAccept",
    "Accept",
)
rule_order.order(*reversed(relay_priorities))


opening_priorities = enum.Enum(
    "StrongTwoClubs",
    "NotrumpOpening",
    "LongestMajor",
    "HigherMajor",
    "LowerMajor",
    "LongestMinor",
    "HigherMinor",
    "LowerMinor",
)
rule_order.order(*reversed(opening_priorities))


class Opening(Rule):
    annotations = annotations.Opening
    preconditions = NoOpening()


class OneLevelSuitOpening(Opening):
    shared_constraints = OpeningRuleConstraint()
    annotations_per_call = {
        '1C': annotations.BidClubs,
        '1D': annotations.BidDiamonds,
        '1H': annotations.BidHearts,
        '1S': annotations.BidSpades,
    }
    # FIXME: This shadows the "annotations" module for the rest of this class scope!
    annotations = annotations.OneLevelSuitOpening
    constraints = {
        '1C': (clubs >= 3, opening_priorities.LowerMinor),
        '1D': (diamonds >= 3, opening_priorities.HigherMinor),
        '1H': (hearts >= 5, opening_priorities.LowerMajor),
        '1S': (spades >= 5, opening_priorities.HigherMajor),
    }
    conditional_priorities_per_call = {
        '1C': [
            (clubs > diamonds, opening_priorities.LongestMinor),
            (z3.And(clubs == 3, diamonds == 3), opening_priorities.LongestMinor),
        ],
        '1D': [(diamonds > clubs, opening_priorities.LongestMinor)],
        '1H': [(hearts > spades, opening_priorities.LongestMajor)],
        '1S': [(spades > hearts, opening_priorities.LongestMajor)],
    }


class NotrumpOpening(Opening):
    annotations = annotations.NotrumpSystemsOn
    constraints = {
        '1N': z3.And(points >= 15, points <= 17, balanced),
        '2N': z3.And(points >= 20, points <= 21, balanced)
    }
    priority = opening_priorities.NotrumpOpening


class StrongTwoClubs(Opening):
    annotations = annotations.StrongTwoClubOpening
    call_names = '2C'
    shared_constraints = points >= 22  # FIXME: Should support "or 9+ winners"
    priority = opening_priorities.StrongTwoClubs


class Response(Rule):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.Opening)


class ResponseToOneLevelSuitedOpen(Response):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.OneLevelSuitOpening)


new_one_level_suit_responses = enum.Enum(
    "LongestNewMajor",
    "OneSpadeWithFive",
    "OneHeartWithFive",
    # We prefer 1D over 4-card majors when bidding up the line.
    "OneDiamondWithPossibleMajor",
    "OneHeartWithFour",
    "OneSpadeWithFour",
    "OneDiamond",
)
rule_order.order(*reversed(new_one_level_suit_responses))


new_one_level_major_responses = set([
    new_one_level_suit_responses.LongestNewMajor,
    new_one_level_suit_responses.OneSpadeWithFive,
    new_one_level_suit_responses.OneHeartWithFive,
    new_one_level_suit_responses.OneHeartWithFour,
    new_one_level_suit_responses.OneSpadeWithFour,
])


# We don't include OneDiamondWithPossibleMajor in this as it only
# matters relative to 4-card major bids.
new_one_level_minor_responses = set([new_one_level_suit_responses.OneDiamond])


class OneLevelNewSuitResponse(Rule):
    # If partner opened, regardless of the bidding, its always only 6 points to mention a new suit at the one level.
    preconditions = Opened(positions.Partner)
    shared_constraints = points >= 6
    constraints = {
        '1D': (diamonds >= 4, new_one_level_suit_responses.OneDiamond),
        '1H': (hearts >= 4, new_one_level_suit_responses.OneHeartWithFour),
        '1S': (spades >= 4, new_one_level_suit_responses.OneSpadeWithFour),
    }
    # FIXME: 4 should probably be the special case and 5+ be the default priority.
    conditional_priorities_per_call = {
        '1D': [(z3.Or(hearts == 4, spades == 4), new_one_level_suit_responses.OneDiamondWithPossibleMajor)],
        '1H': [
            (z3.And(hearts >= 5, hearts > spades), new_one_level_suit_responses.LongestNewMajor),
            (hearts >= 5, new_one_level_suit_responses.OneHeartWithFive),
        ],
        '1S': [(spades >= 5, new_one_level_suit_responses.OneSpadeWithFive)]
    }


class OneNotrumpResponse(ResponseToOneLevelSuitedOpen):
    call_names = '1N'
    # For minors this can be up to 12 hcp?  If we're 4.3.3.3 what better bid do we have?
    shared_constraints = points >= 6


class RaiseResponse(ResponseToOneLevelSuitedOpen):
    preconditions = [
        RaiseOfPartnersLastSuit(),
        LastBidHasAnnotation(positions.Partner, annotations.Opening)
    ]


raise_responses = enum.Enum(
    "MajorLimit",
    "MajorMinimum",

    "MinorLimit",
    "MinorMinimum",
)
rule_order.order(*reversed(raise_responses))


major_raise_responses = set([
    raise_responses.MajorLimit,
    raise_responses.MajorMinimum,
])


minor_raise_responses = set([
    raise_responses.MinorLimit,
    raise_responses.MinorMinimum,
])


minimum_raise_responses = set([
    raise_responses.MinorMinimum,
    raise_responses.MajorMinimum,
])


class MinimumRaise(RaiseResponse):
    priorities_per_call = {
        ('2C', '2D'): raise_responses.MinorMinimum,
        ('2H', '2S'): raise_responses.MajorMinimum,
    }
    shared_constraints = [
        MinimumCombinedLength(8),
        MinimumCombinedSupportPoints(18),
        # For the same reasons as described in LimitRaise, this bid is truly limited.
        # At 10 hcp, LimitRaise should apply, and we do not want to absorb any holes
        # which might occur above a limit raise.
        MaximumSupportPointsForPartnersLastSuit(9),
    ]


class LimitRaise(RaiseResponse):
    preconditions = InvertedPrecondition(LastBidHasAnnotation(positions.RHO, annotations.TakeoutDouble))
    priorities_per_call = {
        ('3C', '3D'): raise_responses.MinorLimit,
        ('3H', '3S'): raise_responses.MajorLimit,
    }
    annotations = annotations.LimitRaise
    shared_constraints = [
        MinimumCombinedLength(8),
        # We shouldn't make a limit raise with less than 6 HCP
        # even with a large number of support points.
        points >= 6, # FIXME: This leaves a hole with PassResponseToSuitedOpen.
        MinimumCombinedSupportPoints(22),
        # This bid is truly limited.  Above 12 points we should either
        # mention a new suit or bid NT (Jacoby2N for majors).
        # We could instead give this bid a very low priority when
        # above 12 hcp, but limiting it directly seems slightly cleaner (and makes none-finding possible).
        MaximumSupportPointsForPartnersLastSuit(12),
    ]


class MajorJumpToGame(RaiseResponse):
    call_names = ['4H', '4S']
    shared_constraints = [
        MinimumCombinedLength(10),
        points < 10
    ]


class ThreeNotrumpMajorResponse(ResponseToOneLevelSuitedOpen):
    preconditions = LastBidHasStrain(positions.Partner, suit.MAJORS)
    call_names = '3N'
    # This is a very specific range per page 43.
    # With 27+ points, do we need to worry about stoppers in RHO's suit?
    shared_constraints = [balanced, points >= 15, points <= 17]


class NotrumpResponseToMinorOpen(ResponseToOneLevelSuitedOpen):
    preconditions = [
        LastBidHasStrain(positions.Partner, suit.MINORS),
        InvertedPrecondition(LastBidHasAnnotation(positions.RHO, annotations.TakeoutDouble)),
    ]
    constraints = {
        '2N': z3.And(points >= 13, points <= 15),
        # The book says 16-18 for this bid, but with 4.3.3.3 after 1C we have no choice
        # at high enough point levels we'll just start bidding slams directly.  Until then 3N is what we have.
        '3N': z3.And(points >= 16),
    }
    shared_constraints = balanced


class Jordan(ResponseToOneLevelSuitedOpen):
    preconditions = LastBidHasAnnotation(positions.RHO, annotations.TakeoutDouble)
    call_names = '2N'
    shared_constraints = [
        MinimumCombinedLength(8, use_partners_last_suit=True),
        MinimumCombinedSupportPoints(22, use_partners_last_suit=True),
    ]


class ResponseAfterRHOTakeoutDouble(ResponseToOneLevelSuitedOpen):
    preconditions = LastBidHasAnnotation(positions.RHO, annotations.TakeoutDouble)


class RedoubleResponseAfterRHOTakeoutDouble(ResponseAfterRHOTakeoutDouble):
    call_names = 'XX'
    shared_constraints = MinimumCombinedPoints(22)


class JumpRaiseResponseToAfterRHOTakeoutDouble(RaiseResponse):
    preconditions = LastBidHasAnnotation(positions.RHO, annotations.TakeoutDouble)
    call_names = ['3C', '3D', '3H', '3S']
    shared_constraints = MinimumCombinedLength(9)


class JumpShift(object):
    preconditions = [
        UnbidSuit(),
        JumpFromLastContract(exact_size=1)
    ]


class JumpShiftResponseToOpenAfterRHODouble(JumpShift, ResponseAfterRHOTakeoutDouble):
    call_names = Call.suited_names_between('2D', '3H')
    shared_constraints = [
        points >= 5,
        MinLength(6),
        TwoOfTheTopThree()
    ]


defenses_against_takeout_double = [
    Jordan,
    RedoubleResponseAfterRHOTakeoutDouble,
    JumpRaiseResponseToAfterRHOTakeoutDouble,
    JumpShiftResponseToOpenAfterRHODouble,
]
rule_order.order(*reversed(defenses_against_takeout_double))


# FIXME: We should bid longer suits when possible, up the line for 4 cards.
# we don't currently bid 2D over 2C when we have longer diamonds.
new_two_level_suit_responses = enum.Enum(
    "TwoClubs",
    "TwoDiamonds",
    "TwoHearts",
    "TwoSpades",
)
rule_order.order(*reversed(new_two_level_suit_responses))


new_two_level_minor_responses = set([
    new_two_level_suit_responses.TwoClubs,
    new_two_level_suit_responses.TwoDiamonds,
])


new_two_level_major_responses = set([
    new_two_level_suit_responses.TwoHearts,
    new_two_level_suit_responses.TwoSpades,
])

new_minor_responses = new_one_level_minor_responses | new_two_level_minor_responses


class NewSuitAtTheTwoLevel(ResponseToOneLevelSuitedOpen):
    preconditions = [
        UnbidSuit(),
        NotJumpFromLastContract()
    ]
    constraints = {
        '2C' : (clubs >= 4, new_two_level_suit_responses.TwoClubs),
        '2D' : (diamonds >= 4, new_two_level_suit_responses.TwoDiamonds),
        '2H' : (hearts >= 5, new_two_level_suit_responses.TwoHearts),
        '2S' : (spades >= 5, new_two_level_suit_responses.TwoSpades),
    }
    shared_constraints = MinimumCombinedPoints(22)


rule_order.order(
    # Don't jump directly to some high part score or game if we have a second suit to mention first, we might miss slam.
    natural_minor_part_scores | natural_exact_minor_games,
    new_two_level_suit_responses,
)


class ResponseToMajorOpen(ResponseToOneLevelSuitedOpen):
    preconditions = [
        LastBidHasStrain(positions.Partner, suit.MAJORS),
        InvertedPrecondition(LastBidHasAnnotation(positions.Partner, annotations.Artificial))
    ]


class PassResponseToSuitedOpen(ResponseToOneLevelSuitedOpen):
    preconditions = LastBidWas(positions.RHO, 'P')
    call_names = 'P'
    # SuitGameIsRemote would imply that we have < 4 hcp, but conventionally we may pass with 5 hcp.
    # To avoid creating a hole, we if we don't have either 6 hcp or 6 support points we may pass.
    shared_constraints = ConstraintOr(MaximumSupportPointsForPartnersLastSuit(5), points <= 5)


# Due to the Or above, we need to order PassResponseToSuitedOpen relative to raises and game jumps.
rule_order.order(
    PassResponseToSuitedOpen,
    minimum_raise_responses,
    MajorJumpToGame,
)


jacoby_2n = enum.Enum(
    "Jacoby2NWithFour",
    "Jacoby2NWithThree",
)
rule_order.order(*reversed(jacoby_2n))


class Jacoby2N(ResponseToMajorOpen):
    preconditions = LastBidWas(positions.RHO, 'P')
    call_names = '2N'
    conditional_priorities = [
        (SupportForPartnerLastBid(4), jacoby_2n.Jacoby2NWithFour)
    ]
    shared_constraints = [
        # The book says 14+, but this needs to be 13 hcp or there is a hole above limit raise.
        points >= 13,
        # FIXME: We should use a conditional priority to make Jacoby2N with only
        # 3-card trump support lower priority than mentioning a new suit.
        SupportForPartnerLastBid(3),
    ]
    priority = jacoby_2n.Jacoby2NWithThree
    annotations = annotations.Jacoby2N


class ResponseToJacoby2N(Rule):
    # Bids above 4NT are either natural or covered by other conventions.
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.Jacoby2N)
    category = categories.Gadget


class SingletonResponseToJacoby2N(ResponseToJacoby2N):
    preconditions = InvertedPrecondition(RebidSameSuit())
    call_names = ['3C', '3D', '3H', '3S']
    shared_constraints = MaxLength(1)
    annotations = annotations.Artificial
    priorities_per_call = lower_calls_first(call_names)


class SolidSuitResponseToJacoby2N(ResponseToJacoby2N):
    preconditions = InvertedPrecondition(RebidSameSuit())
    call_names = ['4C', '4D', '4H', '4S']
    shared_constraints = [MinLength(5), ThreeOfTheTopFiveOrBetter()]


class SlamResponseToJacoby2N(ResponseToJacoby2N):
    preconditions = RebidSameSuit()
    call_names = ['3C', '3D', '3H', '3S']
    shared_constraints = points >= 18


class MinimumResponseToJacoby2N(ResponseToJacoby2N):
    preconditions = RebidSameSuit()
    call_names = ['4C', '4D', '4H', '4S']
    shared_constraints = NO_CONSTRAINTS


class NotrumpResponseToJacoby2N(ResponseToJacoby2N):
    call_names = '3N'
    shared_constraints = points > 15 # It's really 15-17


jacoby_2n_responses= rule_order.order(
    MinimumResponseToJacoby2N,
    NotrumpResponseToJacoby2N,
    SlamResponseToJacoby2N,
    # Currently favoring features over slam interest.  Unclear if that's correct?
    all_priorities_for_rule(SingletonResponseToJacoby2N),
    SolidSuitResponseToJacoby2N,
)


class JumpShiftResponseToOpen(JumpShift, ResponseToOneLevelSuitedOpen):
    preconditions = InvertedPrecondition(LastBidHasAnnotation(positions.RHO, annotations.TakeoutDouble))

    # Jumpshifts must be below game and are off in competition so
    # 1S P 3H is the highest available response jumpshift.
    call_names = Call.suited_names_between('2D', '3H')
    # FIXME: Shouldn't this be MinHighCardPoints?
    shared_constraints = [points >= 19, MinLength(5)]


class ShapeForNegativeDouble(Constraint):
    def expr(self, history, call):
        call_string = '%s %s' % (history.partner.last_call.name, history.rho.last_call.name)
        return {
            '1C 1D': z3.And(hearts >= 4, spades >= 4),
            '1C 1H': spades == 4,
            '1C 1S': z3.And(diamonds >= 3, hearts >= 4),
            '1C 2D': z3.And(hearts >= 4, spades >= 4),
            '1C 2H': z3.And(diamonds >= 3, spades >= 4),
            '1C 2S': z3.And(diamonds >= 3, hearts >= 4),
            '1D 1H': spades == 4,
            '1D 1S': z3.And(clubs >= 3, hearts >= 4),
            '1D 2C': z3.And(hearts >= 4, spades >= 4),
            '1D 2H': z3.And(clubs >= 3, spades >= 4),
            '1D 2S': z3.And(clubs >= 3, hearts >= 4),
            '1H 1S': z3.And(clubs >= 3, diamonds >= 3), # Probably promises 4+ in both minors?
            '1H 2C': z3.And(diamonds >= 3, spades >= 4),
            '1H 2D': z3.And(clubs >= 3, spades >= 4),
            '1H 2S': z3.And(clubs >= 3, diamonds >= 3),
            '1S 2C': z3.And(diamonds >= 3, hearts >= 4),
            '1S 2D': z3.And(clubs >= 3, hearts >= 4),
            '1S 2H': z3.And(clubs >= 3, diamonds >= 3),
        }[call_string]


class NegativeDouble(ResponseToOneLevelSuitedOpen):
    call_names = 'X'
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.OneLevelSuitOpening),
        LastBidHasSuit(positions.Partner),
        LastBidHasSuit(positions.RHO),
        # A hackish way to make sure Partner and RHO did not bid the same suit.
        InvertedPrecondition(LastBidHasAnnotation(positions.RHO, annotations.Artificial)),
    ]
    shared_constraints = ShapeForNegativeDouble()
    annotations = annotations.NegativeDouble


class OneLevelNegativeDouble(NegativeDouble):
    preconditions = LastBidHasLevel(positions.RHO, 1)
    shared_constraints = points >= 6


class TwoLevelNegativeDouble(NegativeDouble):
    preconditions = LastBidHasLevel(positions.RHO, 2)
    shared_constraints = points >= 8


negative_doubles = set([OneLevelNegativeDouble, TwoLevelNegativeDouble])


# aka OpenerRebidAfterNegativeDouble.
class ResponseToNegativeDouble(Rule):
    category = categories.Gadget # FIXME: Is this right?
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.NegativeDouble)


class CuebidReponseToNegativeDouble(ResponseToNegativeDouble):
    preconditions = [
        CueBid(positions.LHO),
        NotJumpFromLastContract(),
    ]
    # Min: 1C 1D X P 2D, Max: 1C 2S X 3S
    # Unclear if a cuebid of 2D ever makes sense since
    # we'll know they're 4-4 in the majors and can choose between a minor game and NT?
    call_names = Call.suited_names_between('2D', '3S')
    shared_constraints = points >= 19


class NewSuitResponseToNegativeDouble(ResponseToNegativeDouble):
    preconditions = [
        NotJumpFromLastContract(),
        UnbidSuit(),
    ]
    # Min: 1C 1D X P 1H, Max: 1C 2S X P 3H
    call_names = Call.suited_names_between('1H', '3H')
    shared_constraints = MinLength(4)


rule_order.order(
    DefaultPass,
    NewSuitResponseToNegativeDouble,
)


class RaiseResponseToNegativeDouble(ResponseToNegativeDouble):
    preconditions = [
        PartnerHasAtLeastLengthInSuit(4),
        NotJumpFromLastContract(),
    ]
    # Min: 1C 1D X P 1H, Max: 1C 2S X P 3H
    priorities_per_call = {
        # FIXME: It's a bit awkward to re-use raise_responses here.
        ('2C', '2D',
         '3C', '3D'): raise_responses.MinorMinimum,
        ('1H', '1S',
         '2H', '2S',
         '3H'      ): raise_responses.MajorMinimum,
    }
    shared_constraints = MinimumCombinedLength(8)


# FIXME: Should this be a forced-only response?  Should the unforced variant show points? stoppers?
class NotrumpResponseToNegativeDouble(ResponseToNegativeDouble):
    preconditions = NotJumpFromLastContract()
    call_names = ['1N', '2N']
    shared_constraints = balanced


rule_order.order(
    raise_responses.MinorMinimum,
    NotrumpResponseToNegativeDouble,
    raise_responses.MajorMinimum,
)


class JumpResponseToNegativeDouble(ResponseToNegativeDouble):
    preconditions = JumpFromLastContract(exact_size=1)
    shared_constraints = points >= 16


negative_double_jump_responses = enum.Enum(
    "RaiseMajor",
    "NewMajor",
    "Notrump",
    "RaiseMinor",
    "NewMinor",
)
rule_order.order(*reversed(negative_double_jump_responses))


# FIXME: This is identical to JumpShiftByOpener and can be removed.
class JumpNewSuitResponseToNegativeDouble(JumpResponseToNegativeDouble):
    preconditions = UnbidSuit()
    # Min: 1C 1D X P 2H, Max: 1C 2H X P 3S
    priorities_per_call = {
        # I don't think major and minor can ever occur at the same time.
        # This diffence exists only for ordering with JumpNotrumpResonse.
        ('2H', '2S'): negative_double_jump_responses.NewMajor,
        ('3C', '3D'): negative_double_jump_responses.NewMinor,
        ('3H', '3S'): negative_double_jump_responses.NewMajor,
    }
    shared_constraints = MinLength(4)


class JumpRaiseResponseToNegativeDouble(JumpResponseToNegativeDouble):
    preconditions = PartnerHasAtLeastLengthInSuit(4),
    # Min: 1C 1D X P 2H, Max: 1C 2S X P 4H
    priorities_per_call = {
        ('2H', '2S'): negative_double_jump_responses.RaiseMajor,
        ('3C', '3D'): negative_double_jump_responses.RaiseMinor,
        ('3H', '3S'): negative_double_jump_responses.RaiseMajor,
        ('4C', '4D'): negative_double_jump_responses.RaiseMinor,
        ('4H'      ): negative_double_jump_responses.RaiseMajor,
    }
    shared_constraints = MinimumCombinedLength(8)


rule_order.order(
    raise_responses,
    negative_double_jump_responses,
)


class JumpNotrumpResponseToNegativeDouble(JumpResponseToNegativeDouble):
    call_names = '2N'
    # If this bid promised balanced, it would be exactly 18, as otherwise
    # we would have opened 1N if we were balanced.
    # But we still shouldn't have any voids.  With a void we should be jumping to some suit.
    # If this bid had no constraints, then minor jump raises are impossible.
    shared_constraints = MinLength(1, suit.SUITS)
    priority = negative_double_jump_responses.Notrump


rule_order.order(
    NotrumpResponseToNegativeDouble,
    negative_double_jump_responses.Notrump,
)

# Cuebid response is for when we're going to at least game and possibly slam and is basically our highest priority.
rule_order.order(
    natural_bids,
    CuebidReponseToNegativeDouble,
)


class CueBidRebidAfterNegativeDouble(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Me, annotations.NegativeDouble),
        # If we understood better what kind of hand this bid was trying to show, we might be able to cuebid after NT.
        LastBidHasSuit(positions.Partner),
        # I don't think there are any artificial responses to NegativeDoubles, or we should check !artificial here?
        # The Cuebid here is defined as RHO's opening bid, not whatever their most recent one may be.
        CueBid(positions.RHO, use_first_suit=True),
    ]
    # Min: 1D 1H X P 2C P 2H, Max: 1H 2S X P 3D P 3S
    call_names = Call.suited_names_between('2H', '3S')
    # Shows slam interest, but in which suit?
    shared_constraints = MinimumSupportPointsForPartnersLastSuit(15) # How big should this really be?


# Slam interest is always more fun than natural bidding. :)
rule_order.order(
    natural_bids,
    CueBidRebidAfterNegativeDouble,
)


two_clubs_response_priorities = enum.Enum(
    "SuitResponse",
    "NoBiddableSuit",
    "WaitingResponse",
)
rule_order.order(*reversed(two_clubs_response_priorities))


class ResponseToStrongTwoClubs(Response):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.StrongTwoClubOpening)


class WaitingResponseToStrongTwoClubs(ResponseToStrongTwoClubs):
    call_names = '2D'
    shared_constraints = NO_CONSTRAINTS
    annotations = annotations.Artificial
    priority = two_clubs_response_priorities.WaitingResponse


class SuitResponseToStrongTwoClubs(ResponseToStrongTwoClubs):
    call_names = ['2H', '2S', '3C', '3D']
    shared_constraints = [MinLength(5), TwoOfTheTopThree(), points >= 8]
    # FIXME: These should have ordered conditional priorities, no?
    priority = two_clubs_response_priorities.SuitResponse


class NotrumpResponseToStrongTwoClubs(ResponseToStrongTwoClubs):
    call_names = '2N'
    shared_constraints = points >= 8
    priority = two_clubs_response_priorities.NoBiddableSuit


class OpenerRebid(Rule):
    preconditions = LastBidHasAnnotation(positions.Me, annotations.Opening)


class RebidAfterOneLevelOpen(OpenerRebid):
    # FIXME: Most subclasses here only make sense over a minimum rebid from partner.
    preconditions = LastBidHasAnnotation(positions.Me, annotations.OneLevelSuitOpening),


class NotrumpJumpRebid(RebidAfterOneLevelOpen):
    # See KBB's NotrumpJumpRebid for discussion of cases for this bid.
    # Unclear how this is affected by competition?
    annotations = annotations.NotrumpSystemsOn
    # FIXME: Does this only apply over minors?  What about 1H P 1S P 2N?
    preconditions = JumpFromLastContract(exact_size=1)
    call_names = '2N'
    shared_constraints = [
        points >= 18,
        points <= 19,
        balanced,
    ]


class RebidOneNotrumpByOpener(RebidAfterOneLevelOpen):
    preconditions = InvertedPrecondition(LastBidWas(positions.Partner, 'P'))
    call_names = '1N'
    shared_constraints = NO_CONSTRAINTS


class NotrumpInvitationByOpener(RebidAfterOneLevelOpen):
    preconditions = [NotJumpFromLastContract(), HaveFit()]
    # If we're not balanced, than we'd have a HelpSuitGameTry to use instead.
    call_names = '2N'
    shared_constraints = [points >= 16, balanced]


rule_order.order(
    # Jumping to 3N (if possible) is better than just inviting to game.
    # Unclear if we need a separate rule for this jump or if natural NT is sufficient.
    NotrumpInvitationByOpener,
    natural_exact_notrump_game,
)


opener_one_level_new_major = enum.Enum(
    # Up the line with 4s...
    "NewSuitHearts",
    "NewSuitSpades",
)
rule_order.order(*reversed(opener_one_level_new_major))


class NewOneLevelMajorByOpener(RebidAfterOneLevelOpen):
    preconditions = UnbidSuit()
    # FIXME: Should this prefer Hearts over Spades: 1C P 1D P 1H with 4-4 in majors?
    # If partner is expected to prefer 4-card majors over minors then 1H seems impossible?
    priorities_per_call = {
        '1H': opener_one_level_new_major.NewSuitHearts,
        '1S': opener_one_level_new_major.NewSuitSpades,
    }
    shared_constraints = MinLength(4)


class SecondSuitFromOpener(RebidAfterOneLevelOpen):
    preconditions = [
        NotJumpFromLastContract(),
        UnbidSuit(),
        InvertedPrecondition(HaveFit()),
    ]


opener_higher_level_new_suits = enum.Enum(
    "NewSuitHearts", # If you're 4.0.4.5, prefer the major, no?
    "NewSuitClubs", # If you're 4.4.0.5, up the line...
    "NewSuitDiamonds",
)
rule_order.order(*reversed(opener_higher_level_new_suits))


opener_higher_level_new_minors = set([
    opener_higher_level_new_suits.NewSuitClubs,
    opener_higher_level_new_suits.NewSuitDiamonds,
])

opener_higher_level_new_major = opener_higher_level_new_suits.NewSuitHearts


class NewSuitByOpener(SecondSuitFromOpener):
    preconditions = SuitLowerThanMyLastSuit()
    # If you're 4.4.0.5 and the bidding goes 1S P 1H P, do you prefer 2C or 2D?
    constraints = {
        '2C': (NO_CONSTRAINTS, opener_higher_level_new_suits.NewSuitClubs),
        '2D': (NO_CONSTRAINTS, opener_higher_level_new_suits.NewSuitDiamonds),
        '2H': (NO_CONSTRAINTS, opener_higher_level_new_suits.NewSuitHearts),
        # 2S would necessarily be a reverse, or a jump shift, and is not covered by this rule.

        '3C': (MinimumCombinedPoints(25), opener_higher_level_new_suits.NewSuitClubs),
        '3D': (MinimumCombinedPoints(25), opener_higher_level_new_suits.NewSuitDiamonds),
        '3H': (MinimumCombinedPoints(25), opener_higher_level_new_suits.NewSuitHearts),
        # 3S would necessarily be a reverse, or a jump shift, and is not covered by this rule.
    }
    shared_constraints = MinLength(4)


reverse_preconditions = [
    InvertedPrecondition(SuitLowerThanMyLastSuit()),
    LastBidHasSuit(positions.Me),
    UnbidSuit(),
    NotJumpFromLastContract(),
]


class MinimumResponseToLimitRaise(OpenerRebid):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.LimitRaise)


class PassResponseToLimitRaise(MinimumResponseToLimitRaise):
    call_names = 'P'
    shared_constraints = (balanced, points <= 14)


class GameAccept(MinimumResponseToLimitRaise):
    preconditions = RaiseOfPartnersLastSuit()
    call_names = ('4H', '4S')
    shared_constraints = NO_CONSTRAINTS  # Accepting game is our default action.


rule_order.order(
    # GameAccept is defined in terms of pass, we could write it the other way around and reverse the priorities.
    GameAccept,
    PassResponseToLimitRaise,
)

rule_order.order(
    # We have various ways to get to slam with a big hand,  Replying 3N here doesn't seem like one of them.
    natural_exact_notrump_game,
    GameAccept,
)


opener_reverses = enum.Enum(
    # FIXME: With 5.0.4.4 which do you reverse to?
    "ReverseSpades",
    "ReverseHearts",
    "ReverseDiamonds",
)
rule_order.order(*reversed(opener_reverses))

opener_reverse_to_a_minor = opener_reverses.ReverseDiamonds,

opener_reverse_to_a_major = set([
    opener_reverses.ReverseSpades,
    opener_reverses.ReverseHearts,
])

class ReverseByOpener(SecondSuitFromOpener):
    preconditions = reverse_preconditions
    annotations = annotations.OpenerReverse
    priorities_per_call = {
        # 2C is never a reverse
        '2D': opener_reverses.ReverseDiamonds,
        '2H': opener_reverses.ReverseHearts,
        '2S': opener_reverses.ReverseSpades,
    }
    shared_constraints = [MinLength(4), points >= 16]


class ForcedMinimumResponseToOpenerReverse(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.OpenerReverse),
        ForcedToBid(),
    ]


# Also known as Ingberman 2NT
class Lebensohl(ForcedMinimumResponseToOpenerReverse):
    call_names = '2N'
    # Priorities imply we have no major to rebid.
    shared_constraints = NO_CONSTRAINTS


major_responses_to_opener_reverse = enum.Enum(
    "WithFive",
    "WithSixOrMore",
)


class ForcedMajorRebid(ForcedMinimumResponseToOpenerReverse):
    # We have a minimum hand, so we never menetioned a 2-level suit before this one.
    call_names = ('2H', '2S')
    # We only need 5-cards to rebid our major, and no additional points.
    shared_constraints = MinLength(5)
    conditional_priorities = [
        (MinLength(6), major_responses_to_opener_reverse.WithSixOrMore),
    ]
    priority = major_responses_to_opener_reverse.WithFive


rule_order.order(
    Lebensohl,
    major_responses_to_opener_reverse,
)

# Ingberman is effectively "pass" in response to a reverse, we'd rather do anything else if we can.
rule_order.order(
    Lebensohl,
    natural_bids,
)


class SupportPartnerSuit(RebidAfterOneLevelOpen):
    preconditions = [
        InvertedPrecondition(RebidSameSuit()),
        RaiseOfPartnersLastSuit(),
    ]


opener_support_majors = enum.Enum(
    "MajorMax",
    "MajorLimit",
    "MajorMin",
)
rule_order.order(*reversed(opener_support_majors))


class SupportPartnerMajorSuit(SupportPartnerSuit):
    constraints = {
        ('2H', '2S'): (NO_CONSTRAINTS, opener_support_majors.MajorMin),
        ('3H', '3S'): (MinimumCombinedSupportPoints(22), opener_support_majors.MajorLimit),
        ('4H', '4S'): (MinimumCombinedSupportPoints(25), opener_support_majors.MajorMax),
    }
    shared_constraints = MinimumCombinedLength(8)


class RebidOriginalSuitByOpener(RebidAfterOneLevelOpen):
    preconditions = [
        LastBidHasAnnotation(positions.Me, annotations.OneLevelSuitOpening),
        RebidSameSuit(),
    ]


class MinimumRebidOriginalSuitByOpener(RebidOriginalSuitByOpener):
    preconditions = NotJumpFromLastContract()


class UnforcedRebidOriginalSuitByOpener(MinimumRebidOriginalSuitByOpener):
    preconditions = InvertedPrecondition(ForcedToBid())
    call_names = ['2C', '2D', '2H', '2S']
    shared_constraints = MinLength(6)


class ForcedRebidOriginalSuitByOpener(MinimumRebidOriginalSuitByOpener):
    preconditions = ForcedToBid()
    call_names = ['2C', '2D', '2H', '2S']
    conditional_priorities = [
        (MinLength(6), UnforcedRebidOriginalSuitByOpener),
    ]
    shared_constraints = MinLength(5)


class UnsupportedRebid(RebidOriginalSuitByOpener):
    preconditions = MaxShownLength(positions.Partner, 0)


opener_unsupported_rebids = enum.Enum(
    "GameForcingMinor",
    "InvitationalMajor",
    "InvitationalMinor",
)
rule_order.order(*reversed(opener_unsupported_rebids))

opener_unsupported_minor_rebid = set([
    opener_unsupported_rebids.GameForcingMinor,
    opener_unsupported_rebids.InvitationalMinor,
])


opener_unsupported_major_rebid = opener_unsupported_rebids.InvitationalMajor


class InvitationalUnsupportedRebidByOpener(UnsupportedRebid):
    preconditions = JumpFromLastContract()
    priorities_per_call = {
        ('3C', '3D'): opener_unsupported_rebids.InvitationalMinor,
        ('3H', '3S'): opener_unsupported_rebids.InvitationalMajor,
    }
    shared_constraints = MinLength(6), points >= 16


# Mentioned as "double jump rebid his own suit", p56.
# Only thing close to an example is h19, p56 which has sufficient HCP for a game (even if not fit).
class GameForcingUnsupportedRebidByOpener(UnsupportedRebid):
    preconditions = JumpFromLastContract()
    # I doubt we want to jump to game w/o support from our partner.  He's shown 6 points...
    # Maybe this is for extremely unbalanced hands, like 7+?
    call_names = ['4C', '4D']
    shared_constraints = MinLength(6), points >= 19
    priority = opener_unsupported_rebids.GameForcingMinor


class HelpSuitGameTry(RebidAfterOneLevelOpen):
    preconditions = [
        NotJumpFromLastContract(),
        HaveFit(),
        UnbidSuit(),
    ]
    # Minimum: 1C,2C,2D, Max: 1C,3C,3S
    call_names = Call.suited_names_between('2D', '3S')
    # Descriptive not placement bid hence points instead of MinimumCombinedPoints.
    shared_constraints = [MinLength(4), Stopper(), points >= 16]
    priorities_per_call = lower_calls_first(call_names)


rule_order.order(
    # No need to help-suit if we already see game:
    all_priorities_for_rule(HelpSuitGameTry),
    GameAccept,
)


opener_jumpshifts = enum.Enum(
    # It's possible to have 0.4.4.5 and we'd rather jump-shift to hearts than diamonds, no?
    # FIXME: 4-card suits should be mentioned up-the-line!
    "JumpShiftToSpades",
    "JumpShiftToHearts",
    "JumpShiftToDiamonds",
    "JumpShiftToClubs",
)
rule_order.order(*reversed(opener_jumpshifts))


opener_jumpshifts_to_minors = set([
    opener_jumpshifts.JumpShiftToDiamonds,
    opener_jumpshifts.JumpShiftToClubs,
])


opener_jumpshifts_to_majors = set([
    opener_jumpshifts.JumpShiftToSpades,
    opener_jumpshifts.JumpShiftToHearts,
])


class JumpShiftByOpener(JumpShift, RebidAfterOneLevelOpen):
    # The lowest possible jumpshift is 1C P 1D P 2H.
    # The highest possible jumpshift is 1S P 2S P 4H
    priorities_per_call = {
        (      '3C', '4C'): opener_jumpshifts.JumpShiftToClubs,
        (      '3D', '4D'): opener_jumpshifts.JumpShiftToDiamonds,
        ('2H', '3H', '4H'): opener_jumpshifts.JumpShiftToHearts,
        ('2S', '3S',     ): opener_jumpshifts.JumpShiftToSpades,
    }
    # FIXME: The book mentions that opener jumpshifts don't always promise 4, especially for 1C P MAJOR P 3D
    shared_constraints = (points >= 19, MinLength(4))


rule_order.order(
    opener_reverse_to_a_minor,
    opener_jumpshifts_to_minors,
)

rule_order.order(
    # Partner can place us into game, we'd rather JumpShift to show our full strength?
    # This should never preclude a game bid, since JumpShifts are always to lower suits.
    natural_games,
    opener_jumpshifts,
)

two_clubs_opener_rebid_priorities = enum.Enum(
    "ThreeLevelNTRebid",
    "SuitedJumpRebid", # This isn't actually comparible with 3N.

    "SuitedRebid", # I think you'd rather bid 2S when available, instead of 2N, right?
    "TwoLevelNTRebid",
)
rule_order.order(*reversed(two_clubs_opener_rebid_priorities))


class OpenerRebidAfterStrongTwoClubs(OpenerRebid):
    preconditions = LastBidWas(positions.Me, '2C')
    # This could also alternatively use annotations.StrongTwoClubOpening


class NotrumpRebidOverTwoClubs(OpenerRebidAfterStrongTwoClubs):
    annotations = annotations.NotrumpSystemsOn
    # These bids are only systematic after a 2D response from partner.
    preconditions = LastBidWas(positions.Partner, '2D')
    constraints = {
        '2N': [points >= 22, two_clubs_opener_rebid_priorities.TwoLevelNTRebid],
        '3N': [points >= 25, two_clubs_opener_rebid_priorities.ThreeLevelNTRebid], # Should this cap at 27?
    }
    shared_constraints = balanced


class OpenerSuitedRebidAfterStrongTwoClubs(OpenerRebidAfterStrongTwoClubs):
    preconditions = [UnbidSuit(), NotJumpFromLastContract()]
    # This maxes out at 4C -> 2C P 3D P 4C
    # If the opponents are competing we're just gonna double them anyway.
    call_names = Call.suited_names_between('2H', '4C')
    # FIXME: This should either have NoMajorFit(), or have priorities separated
    # so that we prefer to support our partner's major before bidding our own new minor.
    shared_constraints = MinLength(5)
    priority = two_clubs_opener_rebid_priorities.SuitedRebid


class OpenerSuitedJumpRebidAfterStrongTwoClubs(OpenerRebidAfterStrongTwoClubs):
    preconditions = [UnbidSuit(), JumpFromLastContract(exact_size=1)]
    # This maxes out at 4C -> 2C P 3D P 5C, but I'm not sure we need to cover that case?
    # If we have self-supporting suit why jump all the way to 5C?  Why not Blackwood in preparation for slam?
    call_names = Call.suited_names_between('3H', '5C')
    shared_constraints = [MinLength(7), TwoOfTheTopThree()]
    priority = two_clubs_opener_rebid_priorities.SuitedJumpRebid


class ResponderRebid(Rule):
    preconditions = [
        Opened(positions.Partner),
        HasBid(positions.Me),
    ]


class OneLevelOpeningResponderRebid(ResponderRebid):
    preconditions = OneLevelSuitedOpeningBook()


class ResponderSuitRebid(OneLevelOpeningResponderRebid):
    preconditions = RebidSameSuit()


class RebidResponderSuitByResponder(ResponderSuitRebid):
    preconditions = [
        InvertedPrecondition(RaiseOfPartnersLastSuit()),
        InvertedPrecondition(LastBidHasAnnotation(positions.Partner, annotations.OpenerReverse))
    ]
    call_names = ['2D', '2H', '2S']
    shared_constraints = [MinLength(6), points >= 6]


rule_order.order(
    natural_nt_part_scores,
    RebidResponderSuitByResponder,
)
rule_order.order(
    # In the rare case of 1C 1D 1H we'd rather mention 1S than rebid our minor.
    RebidResponderSuitByResponder,
    new_one_level_suit_responses,
)


class ThreeLevelSuitRebidByResponder(ResponderSuitRebid):
    preconditions = [
        InvertedPrecondition(RaiseOfPartnersLastSuit()),
        MaxShownLength(positions.Partner, 0),
        MaxShownLength(positions.Me, 5),
    ]
    call_names = ['3C', '3D', '3H', '3S']
    # FIXME: Page 74 says "second round jump bid of partner's major is normally a game force".
    # Seems we should promise a bit more than just 10hcp here, or partner will be left guessing?
    # FIXME: We should want 3o5 or better?  Partner may just leave us here...
    shared_constraints = [
        MinLength(6),
        points >= 10,
    ]


class ResponderSignoffInPartnersSuit(OneLevelOpeningResponderRebid):
    preconditions = [
        InvertedPrecondition(RaiseOfPartnersLastSuit()),
        # z3 is often smart enough to know that partner has 3 in a suit
        # when re-bidding 1N, but that doesn't mean our (unforced) bid
        # of that new suit would be a sign-off!
        # FIXME: Perhaps this should required ForcedToBid()?
        DidBidSuit(positions.Partner),
    ]
    call_names = ['2C', '2D', '2H', '2S']
    shared_constraints = MinimumCombinedLength(7)


# class ResponderSignoffInMinorGame(ResponderRebid):
#     preconditions = [
#         PartnerHasAtLeastLengthInSuit(3),
#         InvertedPrecondition(RebidSameSuit())
#     ]
#     constraints = {
#         '5C': MinimumCombinedPoints(25),
#         '5D': MinimumCombinedPoints(25),
#     }
#     shared_constraints = [MinimumCombinedLength(8), NoMajorFit()]


class ResponderReverse(OneLevelOpeningResponderRebid):
    preconditions = reverse_preconditions
    # Min: 1C,1D,2C,2H, Max: 1S,2D,2S,3H
    call_names = Call.suited_names_between('2H', '3H')
    shared_constraints = [MinLength(4), points >= 12]


class JumpShiftResponderRebid(JumpShift, OneLevelOpeningResponderRebid):
    # Smallest: 1D,1H,1S,3C
    # Largest: 1S,2H,3C,4D (anything above 4D is game)
    call_names = Call.suited_names_between('3C', '4D')
    shared_constraints = [MinLength(4), points >= 14]
    priorities_per_call = lower_calls_first(call_names)


rule_order.order(
    RebidResponderSuitByResponder,
    ThreeLevelSuitRebidByResponder,
    ResponderReverse,
    all_priorities_for_rule(JumpShiftResponderRebid),
)


class FourthSuitForcingPrecondition(Precondition):
    def fits(self, history, call):
        if annotations.FourthSuitForcing in history.annotations:
            return False
        return len(history.us.bid_suits) == 3 and len(history.them.bid_suits) == 0


class SufficientPointsForFourthSuitForcing(Constraint):
    def expr(self, history, call):
        return points >= max(0, points_for_sound_notrump_bid_at_level[call.level] - history.partner.min_points)


fourth_suit_forcing = enum.Enum(
    "TwoLevel",
    "ThreeLevel",
)
# No need for ordering because at most one is available at any time.

class FourthSuitForcing(Rule):
    category = categories.Gadget
    preconditions = [
        LastBidHasSuit(positions.Partner),
        FourthSuitForcingPrecondition(),
        UnbidSuit(),
    ]
    annotations = annotations.FourthSuitForcing
    shared_constraints = [
        SufficientPointsForFourthSuitForcing(),
        ConstraintNot(Stopper()),
    ]


class NonJumpFourthSuitForcing(FourthSuitForcing):
    preconditions = NotJumpFromPartnerLastBid()
    # Smallest: 1D,1H,1S,2C
    # Largest: 1H,2D,3C,3S
    priorities_per_call = {
        ('2C', '2D', '2H', '2S'): fourth_suit_forcing.TwoLevel,
        ('3C', '3D', '3H', '3S'): fourth_suit_forcing.ThreeLevel,
    }


# We'd rather explore for NT than rebid a 5-card major, but with
# six or more, we prefer the major.
rule_order.order(
    major_responses_to_opener_reverse.WithFive,
    fourth_suit_forcing,
    major_responses_to_opener_reverse.WithSixOrMore
)


class TwoSpadesJumpFourthSuitForcing(FourthSuitForcing):
    preconditions = JumpFromPartnerLastBid(exact_size=1)
    call_names = '2S'
    priority = fourth_suit_forcing.TwoLevel


fourth_suit_forcing_response_priorities = enum.Enum(
    "JumpToThreeNotrump",
    "Notrump",
    "DelayedSupport",
    # "SecondSuit",
    "FourthSuit",
)
rule_order.order(*reversed(fourth_suit_forcing_response_priorities))

rebid_response_to_fourth_suit_forcing_priorities = enum.Enum(*Call.suited_names_between('2D', '4H'))
# Rebid is the lowest priority, so we want lower bids to be higher priority, hence the reverse, right?
rule_order.order(*reversed(rebid_response_to_fourth_suit_forcing_priorities))

rule_order.order(
    rebid_response_to_fourth_suit_forcing_priorities,
    fourth_suit_forcing_response_priorities
)

class ResponseToFourthSuitForcing(Rule):
    category = categories.Gadget
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.FourthSuitForcing)


class StopperInFouthSuit(Constraint):
    def expr(self, history, call):
        strain = history.partner.last_call.strain
        return stopper_expr_for_suit(strain)


class NotrumpResponseToFourthSuitForcing(ResponseToFourthSuitForcing):
    preconditions = NotJumpFromLastContract()
    call_names = ['2N', '3N']
    priority = fourth_suit_forcing_response_priorities.Notrump
    shared_constraints = StopperInFouthSuit()


class NotrumpJumpResponseToFourthSuitForcing(ResponseToFourthSuitForcing):
    preconditions = JumpFromLastContract()
    call_names = '3N'
    priority = fourth_suit_forcing_response_priorities.JumpToThreeNotrump
    shared_constraints = [StopperInFouthSuit(), MinimumCombinedPoints(25)]


class DelayedSupportResponseToFourthSuitForcing(ResponseToFourthSuitForcing):
    preconditions = [
        NotJumpFromLastContract(),
        DidBidSuit(positions.Partner),
        # This is our first mention of this suit for it to be "delayed support".
        InvertedPrecondition(DidBidSuit(positions.Me)),
    ]
    call_names = Call.suited_names_between('2D', '4H')
    priority = fourth_suit_forcing_response_priorities.DelayedSupport
    shared_constraints = MinimumCombinedLength(7)


class RebidResponseToFourthSuitForcing(ResponseToFourthSuitForcing):
    preconditions = [
        NotJumpFromLastContract(),
        DidBidSuit(positions.Me),
    ]
    # FIXME: The higher call should show additional length in that suit.
    priorities_per_call = copy_dict(rebid_response_to_fourth_suit_forcing_priorities, Call.suited_names_between('2D', '4H'))
    shared_constraints = NO_CONSTRAINTS


class FourthSuitResponseToFourthSuitForcing(ResponseToFourthSuitForcing):
    preconditions = [
        NotJumpFromLastContract(),
        UnbidSuit(),
    ]
    call_names = Call.suited_names_between('3C', '4S')
    priority = fourth_suit_forcing_response_priorities.FourthSuit
    shared_constraints = [
        MinLength(4),
        SufficientCombinedPoints(),
    ]


# FIXME: We should add an OpenerRebid of 3N over 2C P 2N P to show a minimum 22-24 HCP
# instead of jumping to 5N which just wastes bidding space.
# This is not covered in the book or the SAYC pdf.


class SecondNegative(ResponderRebid):
    preconditions = [
        StrongTwoClubOpeningBook(),
        LastBidWas(positions.Me, '2D'),
        LastBidWas(positions.RHO, 'P'),
        LastBidHasSuit(positions.Partner),
    ]
    call_names = '3C'
    # Denies a fit, shows a max of 3 hcp
    shared_constraints = points < 3
    annotations = annotations.Artificial


nt_response_priorities = enum.Enum(
    "QuantitativeFourNotrumpJump",
    "LongMajorSlamInvitation",
    "MinorGameForceStayman",
    "FourFiveStayman",
    "JacobyTransferToLongerMajor",
    "JacobyTransferToSpadesWithGameForcingValues",
    "JacobyTransferToHeartsWithGameForcingValues",
    "JacobyTransferToHearts",
    "JacobyTransferToSpades",
    "Stayman",
    "NotrumpGameAccept",
    "NotrumpGameInvitation",
    "LongMinorGameInvitation",
    "RedoubleTransferToMinor",
    "TwoSpadesRelay",
    "GarbageStayman",
)
rule_order.order(*reversed(nt_response_priorities))


class NotrumpResponse(Rule):
    category = categories.NotrumpSystem
    preconditions = [
        # 1N overcalls have systems on too, partner does not have to have opened
        LastBidHasAnnotation(positions.Partner, annotations.NotrumpSystemsOn),
    ]


class NotrumpGameInvitation(NotrumpResponse):
    # This is an explicit descriptive rule, not a ToPlay rule.
    # ToPlay is 7-9, but 7 points isn't in game range.
    constraints = { '2N': MinimumCombinedPoints(23) }
    priority = nt_response_priorities.NotrumpGameInvitation


class NotrumpGameAccept(NotrumpResponse):
    # This is an explicit descriptive rule, not a ToPlay rule.
    # FIXME: p13, h30 suggests we should make this jump with 7 in a minor topped by the AK.
    constraints = { '3N': MinimumCombinedPoints(25) }
    priority = nt_response_priorities.NotrumpGameAccept


two_club_stayman_constraint = ConstraintAnd(
    MinimumCombinedPoints(23),
    z3.Or(hearts >= 4, spades >= 4)
)


four_five_stayman_constraint = ConstraintAnd(
    MinimumCombinedPoints(23),
    z3.Or(
        z3.And(hearts == 4, spades == 5),
        z3.And(hearts == 5, spades == 4),
    ),
)

minor_game_force_stayman_constraints = z3.And(
    points >= 13,
    z3.Or(clubs >= 5, diamonds >= 5)
)

# 2C is a very special snowflake and can lead into many sequences, thus it gets its own class.
class TwoLevelStayman(NotrumpResponse):
    annotations = annotations.Stayman
    call_names = '2C'

    shared_constraints = ConstraintOr(
        minor_game_force_stayman_constraints,
        two_club_stayman_constraint,
        # Garbage stayman is a trade-off.  The fewer points you have the less likely
        # your partner will make 1N.  2D with only 6 is better than 1N with only 18 points.
        z3.And(spades >= 3, hearts >= 3,
            z3.Or(diamonds >= 5,
                z3.And(diamonds >= 4, points <= 3)
            ),
        ),
    )
    conditional_priorities = [
        (minor_game_force_stayman_constraints, nt_response_priorities.MinorGameForceStayman),
        (four_five_stayman_constraint, nt_response_priorities.FourFiveStayman),
        (two_club_stayman_constraint, nt_response_priorities.Stayman),
    ]
    priority = nt_response_priorities.GarbageStayman


class BasicStayman(NotrumpResponse):
    annotations = annotations.Stayman
    priority = nt_response_priorities.Stayman
    shared_constraints = [z3.Or(hearts >= 4, spades >= 4)]
    conditional_priorities = [
        # 3-level and stolen stayman still also prefer stayman over transfers with 4-5.
        (four_five_stayman_constraint, nt_response_priorities.FourFiveStayman),
    ]


class ThreeLevelStayman(BasicStayman):
    preconditions = NotJumpFromPartnerLastBid()
    call_names = '3C'
    shared_constraints = MinimumCombinedPoints(25)


class StolenTwoClubStayman(BasicStayman):
    preconditions = LastBidWas(positions.RHO, '2C')
    call_names = 'X'
    shared_constraints = MinimumCombinedPoints(23)


class StolenThreeClubStayman(BasicStayman):
    preconditions = LastBidWas(positions.RHO, '3C')
    call_names = 'X'
    shared_constraints = MinimumCombinedPoints(25)


class NotrumpTransferResponse(NotrumpResponse):
    annotations = annotations.Transfer


class JacobyTransferToHearts(NotrumpTransferResponse):
    preconditions = NotJumpFromPartnerLastBid()
    call_names = ['2D', '3D', '4D']
    shared_constraints = hearts >= 5
    # Two-level transfers have special rules for setting up a game force sequence with 5-5
    conditional_priorities_per_call = {
        '2D': [(z3.And(hearts == spades, points >= 10), nt_response_priorities.JacobyTransferToHeartsWithGameForcingValues)],
    }
    conditional_priorities = [
        (hearts > spades, nt_response_priorities.JacobyTransferToLongerMajor),
    ]
    priority = nt_response_priorities.JacobyTransferToHearts


class JacobyTransferToSpades(NotrumpTransferResponse):
    preconditions = NotJumpFromPartnerLastBid()
    call_names = ['2H', '3H', '4H']
    shared_constraints = spades >= 5
    # Two-level transfers have special rules for setting up a game force sequence with 5-5
    conditional_priorities_per_call = {
        '2H': [(z3.And(hearts == spades, points >= 10), nt_response_priorities.JacobyTransferToSpadesWithGameForcingValues)],
    }
    conditional_priorities = [
        (spades > hearts, nt_response_priorities.JacobyTransferToLongerMajor),
    ]
    priority = nt_response_priorities.JacobyTransferToSpades


class TwoSpadesRelay(NotrumpTransferResponse):
    constraints = {
        '2S': z3.Or(diamonds >= 6, clubs >= 6),
    }
    priority = nt_response_priorities.TwoSpadesRelay


class QuantitativeFourNotrumpJumpConstraint(Constraint):
    def expr(self, history, call):
        # Invites opener to bid 6N if at a maxium, otherwise pass.
        return points + history.partner.max_points >= 33


class QuantitativeFourNotrumpJump(NotrumpResponse):
    call_names = '4N'
    preconditions = JumpFromLastContract()
    shared_constraints = QuantitativeFourNotrumpJumpConstraint()
    priority = nt_response_priorities.QuantitativeFourNotrumpJump
    annotations = annotations.QuantitativeFourNotrumpJump


class ResponseToQuantitativeFourNotrump(Rule):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.QuantitativeFourNotrumpJump)
    constraints = {
        # This is only needed to make the P vs. 5N decision, 6N == 17 is provided by NaturalNotrump.
        'P': points == 15,
        '5N': points == 16,
    }


class AcceptTransfer(Rule):
    category = categories.Relay
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.Transfer),
        NotJumpFromPartnerLastBid(),
    ]
    shared_constraints = NO_CONSTRAINTS
    priority = relay_priorities.Accept
    # FIXME: Should these generically be artifical?  Is a double of a transfer accept lead-directing?


class AcceptTransferToHearts(AcceptTransfer):
    preconditions = LastBidHasStrain(positions.Partner, suit.DIAMONDS)
    call_names = ['2H', '3H']


class AcceptTransferToSpades(AcceptTransfer):
    preconditions = LastBidHasStrain(positions.Partner, suit.HEARTS)
    call_names = ['2S', '3S']


class AcceptTransferToClubs(AcceptTransfer):
    preconditions = LastBidHasStrain(positions.Partner, suit.SPADES)
    call_names = '3C'
    # We aren't actually showing clubs, so maybe a double is lead-directing and thus this is artificial?
    annotations = annotations.Artificial


class SuperAcceptTransfer(Rule):
    category = categories.Relay
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.Transfer),
        JumpFromPartnerLastBid(exact_size=1),
    ]
    # FIXME: This should use support points, but MinimumSupportPointsForPartnersLastSuit will be confused by the transfer.
    shared_constraints = points >= 17
    priority = relay_priorities.SuperAccept


class SuperAcceptTransferToHearts(SuperAcceptTransfer):
    preconditions = LastBidHasStrain(positions.Partner, suit.DIAMONDS)
    call_names = '3H'
    shared_constraints = hearts >=4


class SuperAcceptTransferToSpades(SuperAcceptTransfer):
    preconditions = LastBidHasStrain(positions.Partner, suit.HEARTS)
    call_names = '3S'
    shared_constraints = spades >=4


class ResponseAfterTransferToClubs(Rule):
    category = categories.Relay # Is this right?
    preconditions = [
        LastBidWas(positions.Partner, '3C'),
        LastBidHasAnnotation(positions.Me, annotations.Transfer),
    ]
    constraints = {
        'P': clubs >= 6,
        '3D': diamonds >= 6,
    }
    priority = relay_priorities.Accept # This priority is bogus.


class RebidAfterJacobyTransfer(Rule):
    preconditions = LastBidHasAnnotation(positions.Me, annotations.Transfer)
    # Our initial transfer could have been with 0 points, rebidding shows points.
    shared_constraints = points >= 8


# FIXME: We need this over higher-level transfers as well to replace the NaturalSuited responses.
class SpadesRebidAfterHeartsTransfer(RebidAfterJacobyTransfer):
    preconditions = LastBidWas(positions.Me, '2D')
    # FIXME: We should not need to manually cap 2S.  We can infer that we have < 10 or we would have transfered to hearts first.
    # FIXME: If we had a 6-5 we would raise directly to game instead of bothering to mention the other major?
    constraints = { '2S': z3.And(spades >= 5, points >= 8, points <= 9) }


hearts_rebids_after_spades_transfers = enum.Enum(
    "SlamInterest",
    "NoSlamInterest",
)
rule_order.order(*reversed(hearts_rebids_after_spades_transfers))


class HeartsRebidAfterSpadesTransfer(RebidAfterJacobyTransfer):
    preconditions = LastBidWas(positions.Me, '2H')
    constraints = {
        # A 3H rebid shows slam interest.  Currently assuming that's 13+?
        # Maybe the 3H bid requires_planning?
        '3H': (points >= 13, hearts_rebids_after_spades_transfers.SlamInterest),
        # A jump to 4H and partner choses 4H or 4S, no slam interest. p11
        '4H': (points >= 10, hearts_rebids_after_spades_transfers.NoSlamInterest),
    }
    shared_constraints = hearts >= 5


class NewMinorRebidAfterJacobyTransfer(RebidAfterJacobyTransfer):
    call_names = '3C', '3D'
    # Minors are not worth mentioning after a jacoby transfer unless we have 5 of them and game-going values.
    # FIXME: It seems like this should imply some number of honors in the bid suit, but there may be times
    # when we have 5+ spot cards in a minor and this looks better than bidding 3N.
    shared_constraints = [MinLength(5), MinimumCombinedPoints(25)]


stayman_response_priorities = enum.Enum(
    "HeartStaymanResponse",
    "SpadeStaymanResponse",
    "DiamondStaymanResponse",
    "RedoubleAfterDoubledStayman",
    "PassStaymanResponse",
)
rule_order.order(*reversed(stayman_response_priorities))


class StaymanResponse(Rule):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.Stayman)
    category = categories.NotrumpSystem


class NaturalStaymanResponse(StaymanResponse):
    preconditions = NotJumpFromPartnerLastBid()
    constraints = {
        ('2H', '3H'): (hearts >= 4, stayman_response_priorities.HeartStaymanResponse),
        ('2S', '3S'): (spades >= 4, stayman_response_priorities.SpadeStaymanResponse),
    }


class PassStaymanResponse(StaymanResponse):
    call_names = 'P'
    shared_constraints = NO_CONSTRAINTS
    priority = stayman_response_priorities.PassStaymanResponse


class DiamondStaymanResponse(StaymanResponse):
    preconditions = [
        NotJumpFromPartnerLastBid(),
        # If RHO called a new suit or doubled, pass takes on this meaning.
        LastBidWas(positions.RHO, 'P'),
    ]
    call_names = ['2D', '3D']
    shared_constraints = NO_CONSTRAINTS
    priority = stayman_response_priorities.DiamondStaymanResponse
    annotations = annotations.Artificial


# FIXME: There must be a simpler way to write history-variant rules like this.
# FIXME: This whole rule feels like a special-case penalty double?
class StolenHeartStaymanResponse(StaymanResponse):
    constraints = { 'X': hearts >= 4 }
    priority = stayman_response_priorities.HeartStaymanResponse


class StolenTwoHeartStaymanResponse(StolenHeartStaymanResponse):
    preconditions = LastBidWas(positions.RHO, '2H')


class StolenThreeHeartStaymanResponse(StolenHeartStaymanResponse):
    preconditions = LastBidWas(positions.RHO, '3H')


class StolenSpadeStaymanResponse(StaymanResponse):
    constraints = { 'X': spades >= 4 }
    priority = stayman_response_priorities.SpadeStaymanResponse


class StolenTwoSpadeStaymanResponse(StolenSpadeStaymanResponse):
    preconditions = LastBidWas(positions.RHO, '2S')


class StolenThreeSpadeStaymanResponse(StolenSpadeStaymanResponse):
    preconditions = LastBidWas(positions.RHO, '3S')


class RedoubleAfterDoubledStayman(StaymanResponse):
    preconditions = LastBidWas(positions.RHO, 'X')
    constraints = { 'XX': clubs >= 5 }
    priority = stayman_response_priorities.RedoubleAfterDoubledStayman


class ResponseToOneNotrump(NotrumpResponse):
    preconditions = LastBidWas(positions.Partner, '1N')


class LongMinorGameInvitation(ResponseToOneNotrump):
    call_names = ['3C', '3D']
    shared_constraints = [MinLength(6), TwoOfTheTopThree(), points >= 5]
    # FIXME: Should use the longer suit preference pattern.
    priority = nt_response_priorities.LongMinorGameInvitation


class LongMajorSlamInvitation(ResponseToOneNotrump):
    call_names = ['3H', '3S']
    shared_constraints = [MinLength(6), TwoOfTheTopThree(), points >= 14]
    # FIXME: Should use the longer suit preference pattern.
    priority = nt_response_priorities.LongMajorSlamInvitation


class StaymanRebid(Rule):
    preconditions = LastBidHasAnnotation(positions.Me, annotations.Stayman)
    category = categories.NotrumpSystem


class GarbagePassStaymanRebid(StaymanRebid):
    # GarbageStayman only exists at the 2-level
    preconditions = LastBidWas(positions.Me, '2C')
    call_names = 'P'
    shared_constraints = points <= 7


stayman_rebid_priorities = enum.Enum(
    "MinorGameForceRebid",
    "GameForcingOtherMajor",
    "InvitationalOtherMajor",
)
rule_order.order(*reversed(stayman_rebid_priorities))


class MinorGameForceRebid(StaymanRebid):
    call_names = ['3C', '3D']
    shared_constraints = [MinLength(5), minor_game_force_stayman_constraints]
    priority = stayman_rebid_priorities.MinorGameForceRebid


class OtherMajorRebidAfterStayman(StaymanRebid):
    preconditions = [
        InvertedPrecondition(RaiseOfPartnersLastSuit()),
    ]
    # Rebidding the other major shows 5-4, with invitational or game-force values.
    constraints = {
        '2H': ([points >= 8, hearts == 5, spades == 4], stayman_rebid_priorities.InvitationalOtherMajor),
        '2S': ([points >= 8, spades == 5, hearts == 4], stayman_rebid_priorities.InvitationalOtherMajor),

        # # Use MinimumCombinedPoints instead of MinHighCardPoints as 3-level bids
        # # are game forcing over both 2C and 3C Stayman responses.
        '3H': ([MinimumCombinedPoints(25), hearts == 5, spades == 4], stayman_rebid_priorities.GameForcingOtherMajor),
        '3S': ([MinimumCombinedPoints(25), spades == 5, hearts == 4], stayman_rebid_priorities.GameForcingOtherMajor),
    }


class RedoubleTransferToMinor(NotrumpResponse):
    preconditions = [
        LastBidWas(positions.Partner, '1N'),
        LastBidWas(positions.RHO, 'X'),
    ]
    call_names = 'XX'
    annotations = annotations.Transfer
    category = categories.Relay
    shared_constraints = z3.And(
        z3.Or(diamonds >= 6, clubs >= 6),
        points <= 4, # NT is likely to be uncomfortable.
    )
    priority = nt_response_priorities.RedoubleTransferToMinor


# FIXME: Should share code with AcceptTransfer, except NotJumpFromPartner's LastBid is confused by 'XX'
class AcceptTransferToTwoClubs(Rule):
    category = categories.Relay
    call_names = '2C'
    preconditions = [
        LastBidWas(positions.Partner, 'XX'),
        LastBidWas(positions.RHO, 'P'),
        LastBidHasAnnotation(positions.Partner, annotations.Transfer),
    ]
    annotations = annotations.Artificial
    priority = relay_priorities.Accept
    shared_constraints = NO_CONSTRAINTS


class ResponseAfterTransferToTwoClubs(Rule):
    category = categories.Relay
    preconditions = [
        LastBidWas(positions.Partner, '2C'),
        LastBidHasAnnotation(positions.Me, annotations.Transfer),
    ]
    constraints = {
        'P': clubs >= 6,
        '2D': diamonds >= 6,
    }


class DirectOvercall(Rule):
    preconditions = EitherPrecondition(
            LastBidHasAnnotation(positions.RHO, annotations.Opening),
            AndPrecondition(
                LastBidHasAnnotation(positions.LHO, annotations.Opening),
                LastBidWas(positions.Partner, 'P'),
                InvertedPrecondition(LastBidWas(positions.RHO, 'P'))
            )
        )


balancing_precondition = AndPrecondition(
    LastBidHasAnnotation(positions.LHO, annotations.Opening),
    LastBidWas(positions.Partner, 'P'),
    LastBidWas(positions.RHO, 'P'),
)

class BalancingOvercall(Rule):
    preconditions = balancing_precondition


class StandardDirectOvercall(DirectOvercall):
    preconditions = [
        LastBidHasSuit(positions.RHO),
        NotJumpFromLastContract(),
        UnbidSuit(),
    ]
    shared_constraints = [
        MinLength(5),
        ThreeOfTheTopFiveOrBetter(),
        # With 4 cards in RHO's suit, we're likely to be doubled.
        MaxLengthInLastContractSuit(3),
    ]
    annotations = annotations.StandardOvercall
    forcing = False # We're limited by the fact that we didn't double.  Partner is allowed to pass.


# FIXME: We need finer-grain ordering of suits, no?
# If 4-card 1-level overcalls are allowed, we have a priority problem:
# This will order 5 clubs over 4 spades when both 1S and 2C are available, no?
# If we require 5-card overcalls, whenever we have 2 avaiable, we'll have michaels/unusual 2n instead.
new_suit_overcalls = enum.Enum(
    "LongestMajor",
    "Major",
    "LongestMinor",
    "Minor",
)
rule_order.order(*reversed(new_suit_overcalls))


class OneLevelStandardOvercall(StandardDirectOvercall):
    shared_constraints = points >= 8
    priorities_per_call = {
        '1D': new_suit_overcalls.Minor,
        '1H': new_suit_overcalls.Major,
        '1S': new_suit_overcalls.Major,
    }
    conditional_priorities_per_call = {
        '1H': [(hearts > spades, new_suit_overcalls.LongestMajor)],
        '1S': [(spades >= hearts, new_suit_overcalls.LongestMajor)],
    }

# This is replaced by Cappelletti for now.  We could do that with a category instead.
# class DirectNotrumpDouble(DirectOvercall):
#     preconditions = LastBidWas(positions.RHO, '1N')
#     call_names = 'X'
#     shared_constraints = z3.And(points >= 15, points <= 17, balanced)


class TwoLevelStandardOvercall(StandardDirectOvercall):
    shared_constraints = points >= 10
    priorities_per_call = {
        '2C': new_suit_overcalls.Minor,
        '2D': new_suit_overcalls.Minor,
        '2H': new_suit_overcalls.Major,
        '2S': new_suit_overcalls.Major,
    }
    conditional_priorities_per_call = {
        '2C': [(clubs > diamonds, new_suit_overcalls.LongestMinor)],
        '2D': [(diamonds >= clubs, new_suit_overcalls.LongestMinor)],
        '2H': [(hearts > spades, new_suit_overcalls.LongestMajor)],
        '2S': [(spades >= hearts, new_suit_overcalls.LongestMajor)],
    }


class ResponseToStandardOvercall(Rule):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.StandardOvercall)


# This is nearly identical to TheLaw, it just notes that you have 6 points.
# All it does is cause one test to fail.  It may not be worth having.
class RaiseResponseToStandardOvercall(ResponseToStandardOvercall):
    preconditions = [
        RaiseOfPartnersLastSuit(),
        NotJumpFromLastContract()
    ]
    call_names = Call.suited_names_between('2D', '3S')
    shared_constraints = [
        SupportForPartnerLastBid(3),
        points >= 6,
    ]


class CuebidResponseToStandardOvercall(ResponseToStandardOvercall):
    preconditions = [
        CueBid(positions.LHO),
        NotJumpFromLastContract()
    ]
    call_names = Call.suited_names_between('2C', '3H')
    shared_constraints = [
        SupportForPartnerLastBid(3),
        MinimumSupportPointsForPartnersLastSuit(11),
    ]


class NewSuitResponseToStandardOvercall(ResponseToStandardOvercall):
    preconditions = [
        TheyOpened(),
        LastBidHasAnnotation(positions.Partner, annotations.StandardOvercall),
        NotJumpFromLastContract(),
        UnbidSuit()
    ]
    call_names = Call.suited_names_between('1H', '3S')
    shared_constraints = [
        MinLength(5),
        TwoOfTheTopThree(),
        MinCombinedPointsForPartnerMinimumSuitedRebid(),
    ]


class DirectOvercall1N(DirectOvercall):
    call_names = '1N'
    shared_constraints = [points >= 15, points <= 18, balanced, StopperInRHOSuit()]
    annotations = annotations.NotrumpSystemsOn


class BalancingOvercallOverSuitedOpen(BalancingOvercall):
    preconditions = LastBidHasAnnotation(positions.LHO, annotations.OneLevelSuitOpening)


balancing_notrumps = enum.Enum(
    "OneNotrump",
    "TwoNotrumpJump",
)

class BalancingNotrumpOvercall(BalancingOvercallOverSuitedOpen):
    constraints = {
        '1N': (z3.And(points >= 12, points <= 14), balancing_notrumps.OneNotrump),
        '2N': (z3.And(points >= 19, points <= 21), balancing_notrumps.TwoNotrumpJump),
    }
    shared_constraints = [balanced, StoppersInOpponentsSuits()] # Only RHO has a suit.
    annotations = annotations.NotrumpSystemsOn


class BalancingSuitedOvercall(BalancingOvercallOverSuitedOpen):
    preconditions = [
        NotJumpFromLastContract(),
        UnbidSuit(),
    ]
    constraints = {
        (      '1D', '1H', '1S'): points >= 5,
        ('2C', '2D', '2H', '2S'): points >= 7,
    }
    shared_constraints = [
        MinLength(5),
        ThreeOfTheTopFiveOrBetter(),
        # Even when balancing, we should not have strength in their suit.
        MaxLengthInLastContractSuit(3),
    ]
    forcing = False # We're limited by the fact that we didn't double.  Partner is allowed to pass.


class BalancingJumpSuitedOvercall(BalancingOvercallOverSuitedOpen):
    preconditions = [
        JumpFromLastContract(exact_size=1),
        UnbidSuit(),
    ]
    call_names = Call.suited_names_between('2D', '3H')
    shared_constraints = [
        points >= 12,
        MinLength(6),
        ThreeOfTheTopFiveOrBetter(),
        # Even when balancing, we should not have strength in their suit.
        MaxLengthInLastContractSuit(3),
    ]
    forcing = False # We're limited by the fact that we didn't double.  Partner is allowed to pass.


class MichaelsCuebid(object):
    preconditions = [
        NotJumpFromLastContract(),
        InvertedPrecondition(UnbidSuit()),
        # Michaels is only on if the opponents have only bid one suit.
        UnbidSuitCountRange(3, 3),
    ]
    # FIXME: 3S may force partner to bid 4H with possibly 0 points!
    constraints = {
        ('2C', '2D', '3C', '3D'): z3.And(hearts >= 5, spades >= 5),
        ('2H', '3H'): z3.And(spades >= 5, z3.Or(clubs >= 5, diamonds >= 5)),
        ('2S', '3S'): z3.And(hearts >= 5, z3.Or(clubs >= 5, diamonds >= 5)),
    }
    annotations = annotations.MichaelsCuebid
    # FIXME: Should the hole in this point range be generated by a higher priority bid?
    shared_constraints = z3.Or(z3.And(6 <= points, points <= 12), 15 <= points)


class DirectMichaelsCuebid(MichaelsCuebid, DirectOvercall):
    preconditions = CueBid(positions.RHO)


class BalancingMichaelsCuebid(MichaelsCuebid, BalancingOvercall):
    preconditions = CueBid(positions.LHO)


class MichaelsMinorRequest(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.MichaelsCuebid),
        # The minor is only ambigious if the cuebid was a major.
        LastBidHasStrain(positions.Partner, suit.MAJORS),
        NotJumpFromLastContract(),
    ]
    requires_planning = True
    call_names = ['2N', '4C', '4N']
    annotations = annotations.MichaelsMinorRequest
    shared_constraints = NO_CONSTRAINTS


class ResponseToMichaelsMinorRequest(Rule):
    # FIXME: Should this be on if RHO bid?
    # If RHO bid the other minor is it already obvious which we have?
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.MichaelsMinorRequest)


class SuitResponseToMichaelsMinorRequest(ResponseToMichaelsMinorRequest):
    preconditions = NotJumpFromLastContract()
    call_names = (
        '3C', '3D',
              '4D',
        '5C', '5D',
    )
    shared_constraints = MinLength(5)


class PassResponseToMichaelsMinorRequest(ResponseToMichaelsMinorRequest):
    # The book doesn't cover this, but if 4C was the minor request, lets interpret a pass
    # as meaning "I have clubs" and am weak (game is already remote).
    preconditions = LastBidWas(positions.Partner, '4C')
    call_names = 'P'
    shared_constraints = clubs >= 5


# Pass instead of 5C when we can.
rule_order.order(SuitResponseToMichaelsMinorRequest, PassResponseToMichaelsMinorRequest)


# FIXME: Missing Jump responses to Michael's minor request.
# They're used for showing that we're a big michaels.


class ForcedResponseToMichaelsCuebid(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.MichaelsCuebid),
        LastBidWas(positions.RHO, 'P'),
    ]

# Shared by both michaels and Unusual 2N
class SimplePreference(object):
    preconditions = [
        DidBidSuit(positions.Partner),
        NotJumpFromLastContract(),
    ]
    shared_constraints = [
        MinLength(2),
        LongestOfPartnersSuits(),
    ]


class MichaelsSimplePreferenceResponse(SimplePreference, ForcedResponseToMichaelsCuebid):
    # Min: 1C 2C P 2H, Max: 2S 3S 4H
    call_names = Call.suited_names_between('2H', '4H')


class Unusual2N(Rule):
    preconditions = [
        # Unusual2N only exists immediately after RHO opens.
        LastBidHasAnnotation(positions.RHO, annotations.Opening),
        EitherPrecondition(
            LastBidHasAnnotation(positions.RHO, annotations.OneLevelSuitOpening),
            # FIXME: We should probably only do this when vulnerability is favorable or with more points?
            LastBidHasAnnotation(positions.RHO, annotations.StrongTwoClubOpening),
        ),
    ]
    call_names = '2N'
    # FIXME: We should consider doing mini-max unusual 2N now that we can!
    shared_constraints = [
        Unusual2NShape(),
        points >= 6,
    ]
    annotations = annotations.Unusual2N
    explanation = "5-5 or better in the two lowest unbid suits."


class ForcedResponseToUnusual2N(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.Unusual2N),
        LastBidWas(positions.RHO, 'P'),
    ]


class Unusual2NSimplePreferenceResponse(SimplePreference, ForcedResponseToUnusual2N):
    # Min: 1D 2N P 3C, Max: 1D 2N P 3H
    call_names = ('3C', '3D', '3H')


two_suited_direct_overcalls = set([
    DirectMichaelsCuebid,
    Unusual2N,
])

class TakeoutDouble(Rule):
    call_names = 'X'
    preconditions = [
        LastBidHasSuit(),
        InvertedPrecondition(HasBid(positions.Partner)),
        InvertedPrecondition(LastBidWas(positions.Me, 'X')),
        # LastBidWasNaturalSuit(),
        # LastBidWasBelowGame(),
        UnbidSuitCountRange(2, 3),
    ]
    annotations = annotations.TakeoutDouble
    # If this is the first bid, it seem OK to not have support for unbid suits
    # if this is a re-bid, it seems we should have shape?
    # e.g. 1C 1D P 2D X
    shared_constraints = ConstraintOr(SupportForUnbidSuits(), points >= 17)
    explanation = "Either support for all unbid suits or 17+ hcp."


takeout_double_after_preempt_precondition = AndPrecondition(
    EitherPrecondition(
        LastBidHasAnnotation(positions.RHO, annotations.Preemptive),
        # FIXME: This shouldn't apply when LHO preempts and RHO shows points!
        LastBidHasAnnotation(positions.LHO, annotations.Preemptive),
    ),
    InvertedPrecondition(HasBid(positions.Me)),
)


class OvercallTakeoutDouble(TakeoutDouble):
    # FIXME: Do we need to exclude takeout double rebids by responder?
    preconditions = InvertedPrecondition(Opened(positions.Me))
    shared_constraints = ConstraintOr(SupportForUnbidSuits(), points >= 17)


class OneLevelTakeoutDouble(OvercallTakeoutDouble):
    preconditions = [
        Level(1),
        InvertedPrecondition(takeout_double_after_preempt_precondition),
        InvertedPrecondition(balancing_precondition),
    ]
    # FIXME: Why isn't this 12?  NaturalSuited can only respond to 12+ points currently.
    shared_constraints = points >= 11


class TwoLevelTakeoutDouble(OvercallTakeoutDouble):
    preconditions = [
        Level(2),
        InvertedPrecondition(takeout_double_after_preempt_precondition),
        InvertedPrecondition(balancing_precondition),
    ]
    shared_constraints = points >= 15


standard_takeout_doubles = set([
    OneLevelTakeoutDouble,
    TwoLevelTakeoutDouble,
])


# FIXME: Is this really true at any level?
class TakeoutDoubleAfterPreempt(OvercallTakeoutDouble):
    preconditions = takeout_double_after_preempt_precondition
    shared_constraints = points >= 11


class BalancingDouble(OvercallTakeoutDouble):
    preconditions = [
        Level(1),
        balancing_precondition,
        InvertedPrecondition(takeout_double_after_preempt_precondition),
    ]
    shared_constraints = points >= 8


class ReopeningDouble(TakeoutDouble):
    # These only apply when partner hasn't mentioned a suit, right?
    preconditions = [
        Opened(positions.Me),
        # Above 2S X, seems we need more than opening points?
        MaxLevel(2),
    ]
    # Having 17+ points is not a sufficient reason to takeout later in the auction.
    shared_constraints = [
        # Seems more important to be short in opponents's suit?
        # Book mentions we likely don't want a void in ops suit however?
        MaxLengthInLastContractSuit(1),
        SupportForUnbidSuits(),
    ]


rule_order.order(
    DefaultPass,
    ReopeningDouble,
)


takeout_double_responses = enum.Enum(
    "ThreeNotrump",
    "CuebidResponseToTakeoutDouble",

    "JumpSpadeResonseToTakeoutDouble",
    "JumpHeartResonseToTakeoutDouble",

    "TwoNotrumpJump",

    "JumpDiamondResonseToTakeoutDouble",
    "JumpClubResonseToTakeoutDouble",

    "ThreeCardJumpSpadeResonseToTakeoutDouble",
    "ThreeCardJumpHeartResonseToTakeoutDouble",
    "ThreeCardJumpDiamondResonseToTakeoutDouble",
    "ThreeCardJumpClubResonseToTakeoutDouble",

    "SpadeResonseToTakeoutDouble",
    "HeartResonseToTakeoutDouble",

    "TwoNotrump",
    "OneNotrump",

    "DiamondResonseToTakeoutDouble",
    "ClubResonseToTakeoutDouble",

    "ThreeCardSpadeResonseToTakeoutDouble",
    "ThreeCardHeartResonseToTakeoutDouble",
    "ThreeCardDiamondResonseToTakeoutDouble",
    "ThreeCardClubResonseToTakeoutDouble",
)
rule_order.order(*reversed(takeout_double_responses))


# Response indicates longest suit (excepting opponent's) with 3+ cards support.
# Cheapest level indicates < 10 points.
# NT indicates a stopper in opponent's suit.  1N: 6-10, 2N: 11-12, 3N: 13-16
# Jump bid indicates 10-12 points (normal invitational values)
# cue-bid in opponent's suit is a 13+ michaels-like bid.
class ResponseToTakeoutDouble(Rule):
    preconditions = [
        LastBidWas(positions.RHO, 'P'),
        LastBidHasAnnotation(positions.Partner, annotations.TakeoutDouble),
    ]


class NotrumpResponseToTakeoutDouble(ResponseToTakeoutDouble):
    preconditions = NotJumpFromLastContract()
    constraints = {
        '1N': (points >= 6, takeout_double_responses.OneNotrump),
        '2N': (points >= 11, takeout_double_responses.TwoNotrump),
        '3N': (points >= 13, takeout_double_responses.ThreeNotrump),
    }
    shared_constraints = [balanced, StoppersInOpponentsSuits()]


# FIXME: This could probably be handled by suited to play if we could get the priorities right!
class JumpNotrumpResponseToTakeoutDouble(ResponseToTakeoutDouble):
    preconditions = JumpFromLastContract()
    constraints = {
        '2N': (points >= 11, takeout_double_responses.TwoNotrumpJump),
        '3N': (points >= 13, takeout_double_responses.ThreeNotrump),
    }
    shared_constraints = [balanced, StoppersInOpponentsSuits()]


class SuitResponseToTakeoutDouble(ResponseToTakeoutDouble):
    preconditions = [SuitUnbidByOpponents(), NotJumpFromLastContract()]
    # FIXME: Why is the min-length constraint necessary?
    shared_constraints = [MinLength(3), LongestSuitExceptOpponentSuits()]
    # Need conditional priorities to disambiguate cases like being 1.4.4.4 with 0 points after 1C X P
    # Similarly after 1H X P, with 4 spades and 4 clubs, but with xxxx spades and AKQx clubs, do we bid clubs or spades?
    priorities_per_call = {
        (      '2C', '3C'): takeout_double_responses.ThreeCardClubResonseToTakeoutDouble,
        ('1D', '2D', '3D'): takeout_double_responses.ThreeCardDiamondResonseToTakeoutDouble,
        ('1H', '2H', '3H'): takeout_double_responses.ThreeCardHeartResonseToTakeoutDouble,
        ('1S', '2S'      ): takeout_double_responses.ThreeCardSpadeResonseToTakeoutDouble,
    }
    conditional_priorities_per_call = {
        (      '2C', '3C'): [(clubs >= 4, takeout_double_responses.ClubResonseToTakeoutDouble)],
        ('1D', '2D', '3D'): [(diamonds >= 4, takeout_double_responses.DiamondResonseToTakeoutDouble)],
        ('1H', '2H', '3H'): [(hearts >= 4, takeout_double_responses.HeartResonseToTakeoutDouble)],
        ('1S', '2S'      ): [(spades >= 4, takeout_double_responses.SpadeResonseToTakeoutDouble)],
    }


class JumpSuitResponseToTakeoutDouble(ResponseToTakeoutDouble):
    preconditions = [SuitUnbidByOpponents(), JumpFromLastContract(exact_size=1)]
    # You can have 10 points, but no stopper in opponents suit and only a 3 card suit to bid.
    # 1C X P, xxxx.Axx.Kxx.Kxx
    shared_constraints = [MinLength(3), LongestSuitExceptOpponentSuits(), points >= 10]
    priorities_per_call = {
        (      '3C', '4C'): takeout_double_responses.ThreeCardJumpClubResonseToTakeoutDouble,
        ('2D', '3D', '4D'): takeout_double_responses.ThreeCardJumpDiamondResonseToTakeoutDouble,
        ('2H', '3H', '4H'): takeout_double_responses.ThreeCardJumpHeartResonseToTakeoutDouble,
        ('2S', '3S'      ): takeout_double_responses.ThreeCardJumpSpadeResonseToTakeoutDouble,
    }
    conditional_priorities_per_call = {
        (      '3C', '4C'): [(clubs >= 4, takeout_double_responses.JumpClubResonseToTakeoutDouble)],
        ('2D', '3D', '4D'): [(diamonds >= 4, takeout_double_responses.JumpDiamondResonseToTakeoutDouble)],
        ('2H', '3H', '4H'): [(hearts >= 4, takeout_double_responses.JumpHeartResonseToTakeoutDouble)],
        ('2S', '3S'      ): [(spades >= 4, takeout_double_responses.JumpSpadeResonseToTakeoutDouble)],
    }


class CuebidResponseToTakeoutDouble(ResponseToTakeoutDouble):
    preconditions = [
        CueBid(positions.LHO),
        NotJumpFromLastContract(),
    ]
    priority = takeout_double_responses.CuebidResponseToTakeoutDouble
    call_names = Call.suited_names_between('2C', '3S')
    # FIXME: 4+ in the available majors?
    shared_constraints = [
        points >= 13,
        SupportForPartnersSuits(),
    ]


# NOTE: I don't think we're going to end up needing most of these.
rebids_after_takeout_double = enum.Enum(
    "JumpMajorRaise",
    "MajorRaise",

    "ThreeNotrump",

    "JumpSpadesNewSuit",
    "SpadesNewSuit",
    "JumpHeartsNewSuit",
    "HeartsNewSuit",

    "JumpTwoNotrump",
    "CueBid",
    "TwoNotrump",
    "OneNotrump",

    "JumpMinorRaise",
    "MinorRaise",

    "JumpDiamondsNewSuit",
    "DiamondsNewSuit",
    "JumpClubsNewSuit",
    "ClubsNewSuit",

    "TakeoutDouble",
)
rule_order.order(*reversed(rebids_after_takeout_double))


class RebidAfterTakeoutDouble(Rule):
    # FIXME: These only apply after a minimum (non-jump?) response from partner.
    preconditions = LastBidHasAnnotation(positions.Me, annotations.TakeoutDouble)
    shared_constraints = points >= 17


class PassAfterTakeoutDouble(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Me, annotations.TakeoutDouble),
        LastBidWas(positions.LHO, 'P'), # If LHO bid up, we don't necessarily have < 17hcp.
        LastBidWas(positions.RHO, 'P'),
    ]
    call_names = 'P'
    shared_constraints = points < 17


class RaiseAfterTakeoutDouble(RebidAfterTakeoutDouble):
    preconditions = [
        LastBidWas(positions.RHO, 'P'),
        RaiseOfPartnersLastSuit(),
        NotJumpFromLastContract()
    ]
    # Min: 1C X 1D P 2D, Max: 2S X P 3H P 4H
    # FIXME: Game doesn't seem like a raise here?
    priorities_per_call = {
        (      '3C', '4C'): rebids_after_takeout_double.MinorRaise,
        ('2D', '3D', '4D'): rebids_after_takeout_double.MinorRaise,
        ('2H', '3H', '4H'): rebids_after_takeout_double.MajorRaise,
        ('2S', '3S'      ): rebids_after_takeout_double.MajorRaise,
    }
    shared_constraints = MinLength(4)


class JumpRaiseAfterTakeoutDouble(RebidAfterTakeoutDouble):
    preconditions = [
        RaiseOfPartnersLastSuit(),
        JumpFromPartnerLastBid(exact_size=1)
    ]
    # Min: 1C X 1D P 3D, Max: 2S X P 3D P 5D
    # FIXME: Game doesn't seem like a raise here?
    priorities_per_call = {
        (      '3C', '4C', '5C'): rebids_after_takeout_double.JumpMinorRaise,
        ('2D', '3D', '4D', '5D'): rebids_after_takeout_double.JumpMinorRaise,
        ('2H', '3H', '4H'      ): rebids_after_takeout_double.JumpMajorRaise,
        ('2S', '3S', '4S'      ): rebids_after_takeout_double.JumpMajorRaise,
    }
    shared_constraints = [MinLength(4), points >= 19]


class NewSuitAfterTakeoutDouble(RebidAfterTakeoutDouble):
    preconditions = [
        UnbidSuit(),
        NotJumpFromLastContract(),
        # FIXME: Remove !RaiseOfPartnersLastSuit once SuitResponseToTakeoutDouble implies 4+ (even though it
        # only needs 3+ to make the bid).  Promising only 3 is currently confusing UnbidSuit.
        InvertedPrecondition(RaiseOfPartnersLastSuit()),
    ]
    # Min: 1C X XX P P 1D, Max: 3C X P 3H P 3S
    priorities_per_call = {
        (      '2C', '3C'): rebids_after_takeout_double.ClubsNewSuit,
        ('1D', '2D', '3D'): rebids_after_takeout_double.DiamondsNewSuit,
        ('1H', '2H', '3H'): rebids_after_takeout_double.HeartsNewSuit,
        ('1S', '2S', '3S'): rebids_after_takeout_double.SpadesNewSuit,
    }
    shared_constraints = MinLength(5)


class JumpNewSuitAfterTakeoutDouble(RebidAfterTakeoutDouble):
    preconditions = [
        UnbidSuit(),
        JumpFromLastContract(exact_size=1),
        # FIXME: Remove !RaiseOfPartnersLastSuit once SuitResponseToTakeoutDouble implies 4+ (even though it
        # only needs 3+ to make the bid).  Promising only 3 is currently confusing UnbidSuit.
        InvertedPrecondition(RaiseOfPartnersLastSuit()),
    ]
    # Min: 1C X XX P 2D, Max: 2S X P 3C 5D
    # FIXME: Jumping straight to game seems less useful than a cuebid would?
    priorities_per_call = {
        (      '3C', '4C', '5C'): rebids_after_takeout_double.JumpClubsNewSuit,
        ('2D', '3D', '4D', '5D'): rebids_after_takeout_double.JumpDiamondsNewSuit,
        ('2H', '3H', '4H'      ): rebids_after_takeout_double.JumpHeartsNewSuit,
        ('2S', '3S', '4S'      ): rebids_after_takeout_double.JumpSpadesNewSuit,

    }
    shared_constraints = [MinLength(6), TwoOfTheTopThree(), points >= 21]


class NotrumpAfterTakeoutDouble(RebidAfterTakeoutDouble):
    constraints = {
        '1N': (points >= 18, rebids_after_takeout_double.OneNotrump),
        # 2N depends on whether it is a jump.
        '3N': (points >= 23, rebids_after_takeout_double.ThreeNotrump), # FIXME: Techincally means 9+ tricks.
    }
    # This can't require stoppers, or we have a hole.
    # With 18 hcp and no 5 card suit, no support for partner, we have to have something to bid.


class NonJumpTwoNotrumpAfterTakeoutDouble(RebidAfterTakeoutDouble):
    preconditions = NotJumpFromLastContract()
    call_names = '2N'
    shared_constraints = [points >= 19, StoppersInOpponentsSuits()]
    priority = rebids_after_takeout_double.TwoNotrump


class JumpTwoNotrumpAfterTakeoutDouble(RebidAfterTakeoutDouble):
    preconditions = JumpFromLastContract()
    call_names = '2N'
    shared_constraints = [points >= 21, StoppersInOpponentsSuits()]
    priority = rebids_after_takeout_double.JumpTwoNotrump


class CueBidAfterTakeoutDouble(RebidAfterTakeoutDouble):
    preconditions = [
        NotJumpFromLastContract(),
        # The Cuebid here is defined as RHO's opening bid, not whatever their most recent one may be.
        CueBid(positions.RHO, use_first_suit=True),
    ]
    # Min: 1C X 1D P 2C, unclear what Max should be?
    # 1S X 2H 3D P 3S?  Should we go higher?
    call_names = Call.suited_names_between('2C', '3S')
    # The book says "with slam interest".  Unclear what that means for constraints.
    shared_constraints = points >= 21
    priority = rebids_after_takeout_double.CueBid


class TakeoutDoubleAfterTakeoutDouble(RebidAfterTakeoutDouble):
    call_names = 'X'
    preconditions = [
        LastBidWas(positions.Partner, 'P'),
        MaxLevel(2),
        LastBidHasSuit(),
    ]
    # Doubling a second time shows both 17+ and shortness in the last bid contract.
    # We're asking partner to pick a suit, any suit but don't let them have it.
    shared_constraints = [points >= 17, MaxLengthInLastContractSuit(1)]
    priority = rebids_after_takeout_double.TakeoutDouble



preempt_priorities = enum.Enum(
    "EightCardPreempt",
    "SevenCardPreempt",
    "SixCardPreempt",
)
rule_order.order(*reversed(preempt_priorities))


class PreemptiveOpen(Opening):
    annotations = annotations.Preemptive
    # Never worth preempting in 4th seat.
    preconditions = InvertedPrecondition(LastBidWas(positions.LHO, 'P'))
    constraints = {
        # 2-level preempts should not have a void. (p89)
        # FIXME: p89 also says no outside 4-card major.
        # 3C only promises 6 cards due to 2C being taken for strong bids.
        (      '2D', '2H', '2S', '3C'): (
                ConstraintAnd(
                    MinLength(6),
                    MinLength(1, suit.SUITS),
                    MaxLengthInUnbidMajors(3),
                ),
                preempt_priorities.SixCardPreempt
            ),
        (      '3D', '3H', '3S'): (
                ConstraintAnd(
                    MinLength(7),
                    # h10 and h12 on p86 seem to suggest we should avoid 3-level preempts with 3-card majors.
                    # FIXME: Maybe only in first and second seat?  Maybe this is a planning concern?
                    # FIXME: MaxLengthInUnbidMajors(2), can't work here as we'll just bid the 2-level version instead.
                ),
                preempt_priorities.SevenCardPreempt),
        ('4C', '4D', '4H', '4S'): (MinLength(8), preempt_priorities.EightCardPreempt),
    }
    shared_constraints = [
        ThreeOfTheTopFiveOrBetter(),
        points >= 5,
    ]


weak_preemptive_overcalls = enum.Enum(
    "WeakFourLevel",
    "WeakThreeLevel",
    "WeakTwoLevel",
)
rule_order.order(*reversed(weak_preemptive_overcalls))


preemptive_overcalls = enum.Enum(
    "FourLevel",
    "ThreeLevel",
    "TwoLevel",
)
rule_order.order(*reversed(preemptive_overcalls))


# rule_order.order(
#     # If weak preempts are available, they're the priority.
#     preemptive_overcalls,
#     weak_preemptive_overcalls,
# )


class PreemptiveOvercall(DirectOvercall):
    annotations = annotations.Preemptive
    preconditions = [JumpFromLastContract(), UnbidSuit()]
    constraints = {
        ('2C', '2D', '2H', '2S'): (MinLength(6), preemptive_overcalls.TwoLevel),
        ('3C', '3D', '3H', '3S'): (MinLength(7), preemptive_overcalls.ThreeLevel),
        ('4C', '4D', '4H', '4S'): (MinLength(8), preemptive_overcalls.FourLevel),
    }
    conditional_priorities_per_call = {
        ('2C', '2D', '2H', '2S'): [(points <= 11, weak_preemptive_overcalls.WeakTwoLevel)],
        ('3C', '3D', '3H', '3S'): [(points <= 11, weak_preemptive_overcalls.WeakThreeLevel)],
        ('4C', '4D', '4H', '4S'): [(points <= 11, weak_preemptive_overcalls.WeakFourLevel)],
    }
    shared_constraints = [ThreeOfTheTopFiveOrBetter(), points >= 5]


class ResponseToPreempt(Rule):
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.Preemptive)


# We don't need anything to pass a preempt.  Even with a void in partner's
# suit we can't correct w/o forcing to game.
# This is basically just a version of SuitGameIsRemote w/o the fit requirement.
class PassResponseToPreempt(ResponseToPreempt):
    call_names = 'P'
    # FIXME: Partner can always have up to 16 hcp when preempting.
    # This should be Max over his minimum?
    shared_constraints = NO_CONSTRAINTS


class NewSuitResponseToPreempt(ResponseToPreempt):
    preconditions = [
        UnbidSuit(),
        NotJumpFromLastContract()
    ]
    # FIXME: These need some sort of priority ordering between the calls.
    call_names = Call.suited_names_between('2D', '4D')
    shared_constraints = [
        MinLength(5),
        # Should this deny support for partner's preempt suit?
        # Does this really need 17+ points for a 2-level contract and 20+ for a 3-level?
        # It seems this bid should be more "we have the majority of the points"
        # than that a particular level is safe.  Responding to a 2-level 15+ should be sufficient?
        MinCombinedPointsForPartnerMinimumSuitedRebid(),
    ]


rule_order.order(
    PassResponseToPreempt,
    natural_bids, # This puts the law above passing, which makes us extend preempts preferentially, is that correct?
    NewSuitResponseToPreempt,
)


class PassAfterPreempt(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Me, annotations.Preemptive),
        InvertedPrecondition(ForcedToBid()),
    ]
    call_names = 'P'
    shared_constraints = NO_CONSTRAINTS


class ForcedRebidAfterPreempt(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Me, annotations.Preemptive),
        ForcedToBid(),  # aka, partner mentioned a new suit.
        LastBidWasBelowGame(), # RHO must have passed for us to be forced.
    ]


class ForcedRebidAfterNewSuitResponseToPreempt(ForcedRebidAfterPreempt):
    preconditions = [
        LastBidHasSuit(positions.Partner),
        InvertedPrecondition(LastBidHasAnnotation(positions.Partner, annotations.Artificial)),
    ]


# This applies both after a new suit, or after 2N feature request.
class MinimumRebidOfPreemptSuit(ForcedRebidAfterPreempt):
    preconditions = [
        RebidSameSuit(),
        NotJumpFromLastContract(),
        # FIXME: This is a hack around the LawOfTotalTricks appearing *forcing*
        InvertedPrecondition(RaiseOfPartnersLastSuit()),
    ]
    # Min: 1S 2D P 2H P 3D
    call_names = Call.suited_names_between('3D', '4D')
    shared_constraints = NO_CONSTRAINTS


class RaiseOfPartnersPreemptResponse(ForcedRebidAfterNewSuitResponseToPreempt):
    preconditions = [
        RaiseOfPartnersLastSuit(),
        NotJumpFromLastContract(),
    ]
    # Min: 1S 2D P 2H P 3D, Unclear what the max is.
    call_names = Call.suited_names_between('3D', '4D')
    # FIXME: This can also be made with doubleton honors according to p85
    shared_constraints = MinimumCombinedLength(8)


class NewSuitAfterPreempt(ForcedRebidAfterNewSuitResponseToPreempt):
    preconditions = [
        NotJumpFromLastContract(),
        UnbidSuit(),
    ]
    # Min: 1S 2D P 2H P 2S, Unclear what the max is.
    call_names = Call.suited_names_between('2S', '4D')
    shared_constraints = [points >= 9, MinLength(4)]


class NotrumpAfterPreempt(ForcedRebidAfterNewSuitResponseToPreempt):
    preconditions = NotJumpFromLastContract()
    # Min: 2D P 2H P 2N, Unclear if 3N is viable?
    call_names = ('2N', '3N')
    shared_constraints = points >= 9


# With a minimum we would rather raise his suit than rebid our own.
# With a maximum we would still rather raise, failing that a new suit, and otherwise NT.
rule_order.order(
    natural_bids, # FIXME: Is this right?  Natural rebids make no sense after a preempt.
    MinimumRebidOfPreemptSuit,
    NotrumpAfterPreempt,
    NewSuitAfterPreempt,
    RaiseOfPartnersPreemptResponse,
)


feature_asking_priorities = enum.Enum(
    "Gerber",
    "Blackwood",
)
rule_order.order(*reversed(feature_asking_priorities))

feature_response_priorities = enum.Enum(
    "Gerber",
    "Blackwood",
    "TwoNotrumpFeatureResponse",
)

class Gerber(Rule):
    category = categories.Gadget
    requires_planning = True
    shared_constraints = NO_CONSTRAINTS
    annotations = annotations.Gerber
    priority = feature_asking_priorities.Gerber


class GerberForAces(Gerber):
    call_names = '4C'
    preconditions = [
        LastBidHasStrain(positions.Partner, suit.NOTRUMP),
        InvertedPrecondition(LastBidHasAnnotation(positions.Partner, annotations.Artificial))
    ]


class GerberForKings(Gerber):
    call_names = '5C'
    preconditions = LastBidHasAnnotation(positions.Me, annotations.Gerber)


class ResponseToGerber(Rule):
    category = categories.Relay
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.Gerber),
        NotJumpFromPartnerLastBid(),
    ]
    constraints = {
        '4D': z3.Or(number_of_aces == 0, number_of_aces == 4),
        '4H': number_of_aces == 1,
        '4S': number_of_aces == 2,
        '4N': number_of_aces == 3,
        '5D': z3.Or(number_of_kings == 0, number_of_kings == 4),
        '5H': number_of_kings == 1,
        '5S': number_of_kings == 2,
        '5N': number_of_kings == 3,
    }
    priority = feature_response_priorities.Gerber
    annotations = annotations.Artificial


class Blackwood(Rule):
    category = categories.Gadget
    requires_planning = True
    shared_constraints = NO_CONSTRAINTS
    annotations = annotations.Blackwood
    priority = feature_asking_priorities.Blackwood


class BlackwoodForAces(Blackwood):
    call_names = '4N'
    preconditions = [
        LastBidHasSuit(positions.Partner),
        EitherPrecondition(JumpFromLastContract(), HaveFit())
    ]


class BlackwoodForKings(Blackwood):
    call_names = '5N'
    preconditions = LastBidHasAnnotation(positions.Me, annotations.Blackwood)


class ResponseToBlackwood(Rule):
    category = categories.Relay
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.Blackwood),
        NotJumpFromPartnerLastBid(),
    ]
    constraints = {
        '5C': z3.Or(number_of_aces == 0, number_of_aces == 4),
        '5D': number_of_aces == 1,
        '5H': number_of_aces == 2,
        '5S': number_of_aces == 3,
        '6C': z3.Or(number_of_kings == 0, number_of_kings == 4),
        '6D': number_of_kings == 1,
        '6H': number_of_kings == 2,
        '6S': number_of_kings == 3,
    }
    priority = feature_response_priorities.Blackwood
    annotations = annotations.Artificial


class TwoNotrumpFeatureRequest(ResponseToPreempt):
    category = categories.Gadget
    annotations = annotations.FeatureRequest
    requires_planning = True
    constraints = { '2N': MinimumCombinedPoints(22) }


rule_order.order(
    PassResponseToPreempt,
    TwoNotrumpFeatureRequest,
)


class ResponseToTwoNotrumpFeatureRequest(Rule):
    category = categories.Gadget
    preconditions = LastBidHasAnnotation(positions.Partner, annotations.FeatureRequest)
    priority = feature_response_priorities.TwoNotrumpFeatureResponse


class FeatureResponseToTwoNotrumpFeatureRequest(ResponseToTwoNotrumpFeatureRequest):
    category = categories.Gadget
    preconditions = InvertedPrecondition(RebidSameSuit())
    annotations = annotations.Artificial
    call_names = ['3C', '3D', '3H', '3S']
    # Note: We could have a protected outside honor with as few as 6 points,
    # (QJTxxx in our main suit + Qxx in our outside honor suit)
    # p86 seems to suggest we need 9+ hcp.
    shared_constraints = [points >= 9, ThirdRoundStopper()]


rule_order.order(
    MinimumRebidOfPreemptSuit,
    feature_response_priorities.TwoNotrumpFeatureResponse,
)


class GrandSlamForce(Rule):
    preconditions = [
        LastBidHasSuit(positions.Partner),
        # Since ACBL requires 8hcp to open naturally, I suspect partner has to have opened for GSF to be on.
        LastBidHasAnnotation(positions.Partner, annotations.Opening),
        JumpFromLastContract(), # This is slightly redundant. :)
    ]
    call_names = '5N'
    requires_planning = True
    shared_constraints = NO_CONSTRAINTS
    annotations = annotations.GrandSlamForce


grand_slam_force_responses = enum.Enum(
    "GrandSlam",
    "SmallSlam",
)
rule_order.order(*reversed(grand_slam_force_responses))


class ResponseToGrandSlamForce(Rule):
    preconditions = [
        LastBidHasAnnotation(positions.Partner, annotations.GrandSlamForce),
        RebidSameSuit(),
    ]
    constraints = {
        ('6C', '6D', '6H', '6S'): (NO_CONSTRAINTS, grand_slam_force_responses.SmallSlam),
        ('7C', '7D', '7H', '7S'): (TwoOfTheTopThree(), grand_slam_force_responses.GrandSlam),
    }


rule_order.order(preempt_priorities, opening_priorities)
rule_order.order(natural_bids, preempt_priorities)
rule_order.order(natural_games, nt_response_priorities, natural_slams)
rule_order.order(natural_bids, stayman_response_priorities)
rule_order.order(natural_bids, GarbagePassStaymanRebid)
rule_order.order(natural_bids, PassAfterTakeoutDouble)
rule_order.order(natural_bids, two_clubs_opener_rebid_priorities)
rule_order.order(natural_exact_notrump_game, stayman_rebid_priorities.GameForcingOtherMajor, natural_exact_major_games)
rule_order.order(natural_nt_part_scores, stayman_rebid_priorities.InvitationalOtherMajor, natural_suited_part_scores)
rule_order.order(takeout_double_responses, natural_bids)
rule_order.order(ForcedRebidOriginalSuitByOpener, natural_bids)
rule_order.order(natural_bids, NewSuitResponseToStandardOvercall, CuebidResponseToStandardOvercall)
rule_order.order(RaiseResponseToStandardOvercall, natural_bids)
rule_order.order(DefaultPass, RaiseResponseToStandardOvercall)
rule_order.order(ResponderSignoffInPartnersSuit, natural_bids)
rule_order.order(DefaultPass, ResponderSignoffInPartnersSuit)
rule_order.order(DefaultPass, opening_priorities)
rule_order.order(rebids_after_takeout_double, natural_bids)
rule_order.order(natural_bids, SecondNegative)
rule_order.order(DefaultPass, rebids_after_takeout_double)

rule_order.order(
    DefaultPass,
    RebidOneNotrumpByOpener,
    opener_one_level_new_major,
    opener_support_majors,
)
rule_order.order(
    RebidOneNotrumpByOpener,
    opener_higher_level_new_suits,
)
rule_order.order(
    RebidOneNotrumpByOpener,
    opener_reverses,
)
rule_order.order(
    ForcedRebidOriginalSuitByOpener,
    opener_higher_level_new_suits,
    opener_one_level_new_major,
)
rule_order.order(
    DefaultPass,
    opener_higher_level_new_minors,
    opener_jumpshifts_to_minors,
)
rule_order.order(
    opener_higher_level_new_major,
    opener_reverse_to_a_major,
    opener_jumpshifts_to_majors,
)
rule_order.order(
    opener_reverse_to_a_minor,
    opener_one_level_new_major,
    opener_jumpshifts_to_majors,
)
rule_order.order(
    NotrumpJumpRebid,
    opener_support_majors,
)
rule_order.order(
    # Don't jump to game immediately, even if we have the points for it.
    natural_exact_notrump_game,
    opener_one_level_new_major,
)
rule_order.order(
    ThreeNotrumpMajorResponse,
    new_one_level_major_responses,
)
rule_order.order(
    # FIXME: Why?  If we already see 3N, why FSF?
    natural_exact_notrump_game,
    fourth_suit_forcing,
)
rule_order.order(
    natural_nt_part_scores,
    fourth_suit_forcing.TwoLevel,
)
rule_order.order(
    # FIXME: This seems backwards.
    natural_suited_part_scores,
    fourth_suit_forcing.TwoLevel,
)
rule_order.order(
    fourth_suit_forcing,
    ThreeLevelSuitRebidByResponder,
)
rule_order.order(
    # If we already see game, why use FSF?
    fourth_suit_forcing,
    natural_exact_major_games,
)
rule_order.order(
    DefaultPass,
    # Mention a 4-card major before rebidding a 6-card minor.
    UnforcedRebidOriginalSuitByOpener,
    opener_one_level_new_major,
)
rule_order.order(
    ForcedRebidOriginalSuitByOpener,
    opener_higher_level_new_suits,
)
rule_order.order(
    ForcedRebidOriginalSuitByOpener,
    RebidOneNotrumpByOpener,
    UnforcedRebidOriginalSuitByOpener,
)
rule_order.order(
    # Rebids will only ever consider one suit, so we won't be comparing majors/minors here.
    ForcedRebidOriginalSuitByOpener,
    UnforcedRebidOriginalSuitByOpener,
    opener_unsupported_rebids,
)
rule_order.order(
    # We'd rather mention a new minor (heading towards NT) than rebid one?
    opener_unsupported_rebids.InvitationalMinor,
    opener_higher_level_new_minors,
)
rule_order.order(
    natural_suited_part_scores,
    NotrumpInvitationByOpener,
    all_priorities_for_rule(HelpSuitGameTry),
)
rule_order.order(
    # If we have a new suit to mention, we'd rather do that than sign off in game?
    # Maybe game with stoppers should be higher priority and game without lower?
    # 1S P 2C P 2H seems higher priority than a straight jump to game...
    # but 1S P 2C P 2D doesn't seem very useful if we have everything stopped?
    natural_exact_notrump_game,
    opener_higher_level_new_suits,
)
rule_order.order(
    opener_higher_level_new_suits,
    opener_support_majors,
)
rule_order.order(
    # Definitely rather jump to NT rather than mention a new minor.  Unclear about 2H vs. NT.
    opener_higher_level_new_minors,
    NotrumpJumpRebid,
)
rule_order.order(
    ResponderSignoffInPartnersSuit,
    ResponderReverse,
)
rule_order.order(
    # If we see that game is remote, just stop.
    UnforcedRebidOriginalSuitByOpener,
    natural_passses,
)
rule_order.order(
    # FIXME: This may be unecessary once we have responses to negative doubles.
    # But we'd rather place the contract in a suited part score than in NT.
    RebidOneNotrumpByOpener,
    natural_suited_part_scores,
)
rule_order.order(
    # We'd rather disclose a 6-card major suit than just jump to NT.
    # FIXME: It's possible this is only an issue due to NaturalNotrump missing stoppers!
    natural_exact_notrump_game,
    opener_unsupported_major_rebid,
)
rule_order.order(
    # Showing a second minor seems more useful than showing a longer one.
    opener_unsupported_minor_rebid,
    opener_reverse_to_a_minor,
)
rule_order.order(
    OneNotrumpResponse,
    raise_responses,
)
rule_order.order(
    # We don't need to put this above all raise responses, but it shouldn't hurt.
    raise_responses,
    MajorJumpToGame,
)
rule_order.order(
    DefaultPass,
    OneNotrumpResponse, # Any time we can respond we should.
    new_minor_responses, # But we prefer suits to NT.
    major_raise_responses, # But we'd much rather support our partner's major!
)
rule_order.order(
    OneNotrumpResponse,
    new_two_level_major_responses,
)
rule_order.order(
    # Relays are extremely high priority, this is likely redundant with other orderings.
    natural_bids,
    relay_priorities
)
rule_order.order(
    # Rather jump to NT than mention a new minor.
    new_minor_responses,
    NotrumpResponseToMinorOpen,
    new_one_level_major_responses,
)
rule_order.order(
    new_two_level_minor_responses,
    new_one_level_major_responses,
)
rule_order.order(
    natural_bids,
    two_clubs_response_priorities,
)
rule_order.order(
    natural_bids,
    feature_response_priorities,
)
rule_order.order(
    # We want to start constructive, not just jump to slam.
    natural_slams,
    # FIXME: This should be a group of game-forcing responses, no?
    JumpShiftResponseToOpen,
)
rule_order.order(
    OneNotrumpResponse,
    natural_bids,
)
rule_order.order(
    OneNotrumpResponse,
    OneLevelNegativeDouble,
)
rule_order.order(
    raise_responses,
    JumpShiftResponseToOpen,
)
rule_order.order(
    new_one_level_minor_responses,
    # We'd rather mention a new major than raise partner's minor or mention our own.
    minor_raise_responses,
    new_one_level_major_responses,
    # But we'd rather raise a major than mention a new one.
    major_raise_responses
)
rule_order.order(
    # NegativeDouble is more descriptive than any one-level new suit (when it fits).
    new_one_level_suit_responses,
    OneLevelNegativeDouble,
)
rule_order.order(
    OneNotrumpResponse,
    OneLevelNegativeDouble,
)
# Constructive responses are always better than placement responses.
rule_order.order(
    natural_bids,
    new_one_level_suit_responses,
)
rule_order.order(
    DefaultPass,
    TwoLevelNegativeDouble,
)
rule_order.order(
    OneNotrumpResponse,
    jacoby_2n.Jacoby2NWithThree,
    new_two_level_suit_responses,
)
rule_order.order(
    major_raise_responses,
    jacoby_2n.Jacoby2NWithFour,
)
rule_order.order(
    natural_bids,
    jacoby_2n_responses,
)
rule_order.order(
    new_one_level_suit_responses,
    defenses_against_takeout_double,
)
rule_order.order(
    minimum_raise_responses,
    defenses_against_takeout_double,
    MajorJumpToGame,
)
rule_order.order(
    OneNotrumpResponse,
    NotrumpResponseToMinorOpen,
    defenses_against_takeout_double,
)
# The rebid-after-transfer bids are more descriptive than jumping to NT game.
rule_order.order(
    natural_exact_notrump_game,
    hearts_rebids_after_spades_transfers
)
rule_order.order(
    natural_suited_part_scores,
    SpadesRebidAfterHeartsTransfer
)
rule_order.order(
    natural_exact_notrump_game,
    NewMinorRebidAfterJacobyTransfer
)
rule_order.order(
    # Even a jumpshift to a major seems less descriptive than a 2N rebid.
    opener_jumpshifts,
    NotrumpJumpRebid,
)
rule_order.order(
    # Better to raise partner's major than show minors.
    negative_doubles,
    major_raise_responses,
)
rule_order.order(
    # Better to show a major than raise partner's minor.
    minor_raise_responses,
    negative_doubles,
)
rule_order.order(
    # Better to show points for NT game than mention a new minor?
    new_two_level_minor_responses,
    ThreeNotrumpMajorResponse,
)
rule_order.order(
    natural_nt_part_scores,
    negative_doubles,
)
rule_order.order(
    # If we can rebid, that's always better than escaping to a NT partscore.
    # FIXME: This should be escape_to_nt_partscore instead of natural_nt.
    # This ordering is probably overbroad as written!
    natural_nt_part_scores,
    UnforcedRebidOriginalSuitByOpener,
)
rule_order.order(
    opener_unsupported_major_rebid,
    opener_jumpshifts,
)
rule_order.order(
    # Jumpshift shows 19+ vs. 16+
    all_priorities_for_rule(HelpSuitGameTry),
    opener_jumpshifts,
)
rule_order.order(
    # Rebidding a 6-card major seems better than mentioning any new suit?  Including a new major?
    # FIXME: What about when we're 6-5 in the majors?
    opener_higher_level_new_suits,
    opener_unsupported_major_rebid,
)

# FIXME: This is a very rough approximation, and needs much more refinement
# particularly in the ordering of new majors vs. notrump.
rule_order.order(
    DefaultPass,
    BalancingSuitedOvercall,
    BalancingMichaelsCuebid,
    balancing_notrumps.OneNotrump,
    BalancingDouble,
    balancing_notrumps.TwoNotrumpJump,
    BalancingJumpSuitedOvercall,
)
rule_order.order(
    DefaultPass,
    new_suit_overcalls,
)
rule_order.order(
    # FIXME: This is wrong.  p118, h10 seems to say we should prefer 5-card majors over a takeout double?
    new_suit_overcalls,
    standard_takeout_doubles,
)
rule_order.order(
    new_suit_overcalls,
    TakeoutDoubleAfterPreempt,
)
rule_order.order(
    # FIXME: Is this always true?  What if partner has passed?  Is there a point range at which we'd rather preempt?
    preemptive_overcalls,
    standard_takeout_doubles,
)
rule_order.order(
    # It seems we'd always rather show a major and a minor instead of just a single suit when possible?
    new_suit_overcalls,
    two_suited_direct_overcalls,
)
rule_order.order(
    # Unusual2N and Michaels show two 5 card suits which is better than one.
    # If we have a 5-card major it will always be shown as part of one of these.
    standard_takeout_doubles,
    two_suited_direct_overcalls,
)
rule_order.order(
    # Even when we're weak, we'd rather find a fit with partner, than jump in our own suit.
    weak_preemptive_overcalls,
    two_suited_direct_overcalls,
)
rule_order.order(
    new_suit_overcalls,
    Unusual2N,
)
rule_order.order(
    # FIXME: Is this always true?  What about if partner has passed?
    preemptive_overcalls,
    new_suit_overcalls,
)
rule_order.order(
    DefaultPass,
    preemptive_overcalls,
)
rule_order.order(
    # If we can preempt, that's more descriptive than a standard overcall.
    new_suit_overcalls,
    weak_preemptive_overcalls,
)
rule_order.order(
    # 1N overcall is more descriptive than a takeout double.
    standard_takeout_doubles,
    DirectOvercall1N,
)
rule_order.order(
    ForcedRebidOriginalSuitByOpener,
    NewSuitResponseToNegativeDouble,
    UnforcedRebidOriginalSuitByOpener,
    negative_double_jump_responses,
    CuebidReponseToNegativeDouble,
)

rule_order.order(
    minimum_raise_responses,
    JumpRaiseResponseToNegativeDouble,
    CuebidReponseToNegativeDouble,
)
# Negative doubles possibly show majors, and are more descriptive than NT responses.
rule_order.order(
    NotrumpResponseToMinorOpen,
    negative_doubles,
)
rule_order.order(
    natural_passses,
    all_priorities_for_rule(HelpSuitGameTry),
)
rule_order.order(
    natural_bids,
    ThreeNotrumpMajorResponse,
)
rule_order.order(
    # We'd rather raise a major than rebid our minor.
    opener_unsupported_rebids.InvitationalMinor,
    negative_double_jump_responses.RaiseMajor,
)
