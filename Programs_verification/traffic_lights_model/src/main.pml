/*
 *  This file is part of traffic lights model development and verification.
 *
 *  Copyright (C) 2010  Vladimir Rutsky <altsysrq@gmail.com>
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

  /* Variant 9-13:
   * SN, WE, NE, ES.
   */
  /*
   *               N
   *           2
   *           |       ^
   *           |       |
   *           |     --2-------3
   *            \   /  |
   *  W           4    |          E
   *            /   \  |
   *           /     --1------>
   *           |       |
   *    1 -----3-------0------>
   *           |       |
   *           v       |
   *                   0
   *               S
   *
   */

#define NE 0
#define ES 1
#define SW 2
#define WE 3
#define EW 4

/* Number of traffic lights */
#define N_TRAFFIC_LIGHTS 4

/* Number of intersections */
#define N_OVERLAPS 5

/* Car object */
mtype = { CAR };

/* Cars waiting sign for each traffic light */
chan carsWaiting[N_TRAFFIC_LIGHTS] = [1] of { mtype };

proctype LineTrafficGenerator( byte initTLId )
{
  byte TLId;
  
  TLId = initTLId;
  
  do
  :: carsWaiting[TLId] ! CAR;
  od
}

/* Manager messages */
mtype = { LOCK, INT, RELEASE };

/* overlaps lock/release requests queue.
 * Message contains requestee traffic light identifier.
 */
chan OverlapLockRequests[N_OVERLAPS] = 
  [N_TRAFFIC_LIGHTS] of { mtype, byte };
chan OverlapLockGranted[N_TRAFFIC_LIGHTS] = 
  [0] of { mtype };
chan OverlapReleaseRequests[N_OVERLAPS] = 
  [0] of { mtype };

/* Macro for obtaining intersection resource */
#define lockOverlap( OvId, TLId )   \
  OverlapLockRequests[OvId] ! LOCK(TLId); \
  OverlapLockGranted[TLId] ? INT

/* Macro for releasing intersection resource */
#define unlockOverlap( OvId ) \
  OverlapReleaseRequests[OvId] ! RELEASE

/* Intersection resource manager */
proctype Overlap( byte initOvId )
{
  byte OvId, TLId;

  OvId = initOvId;

endOv:
  do
  :: OverlapLockRequests[OvId] ? LOCK(TLId) ->
    /* Handle request */
    OverlapLockGranted[TLId] ! INT;

    /* Wait for release */
  progressGiveOverlap:
    OverlapReleaseRequests[OvId] ? RELEASE;
  od;
}

/* Traffic lights states */
mtype = { RED, GREEN };

/* Traffic light state */
mtype TLColor[N_TRAFFIC_LIGHTS];

/* Main traffic light process */
proctype TrafficLight( byte initTLId )
{
  byte TLId;
  
  tlId = initTLId;

  assert(TLColor[TLId] == RED);

endTL:
  do
  :: carsWaiting[TLId] ? [CAR] ->
    /* Cars in queue */
  
    /* Lock dependent intersections */
    if
    :: TLId == SN ->
      lockOverlap(0, TLId);
      lockOverlap(1, TLId);
      lockOverlap(2, TLId);
    :: TLId == WE ->
      lockOverlap(0, TLId);
      lockOverlap(3, TLId);
    :: TLId == ES ->
      lockOverlap(2, TLId);
      lockOverlap(3, TLId);
      lockOverlap(4, TLId);
    :: TLId == NE ->
      lockOverlap(1, TLId);
      lockOverlap(4, TLId);
    fi;
    
    /* Allow passing */
  progressPassCar:
    atomic 
    {
      printf("MSC: Traffic light #%d: GREEN\n", TLId);
      TLColor[TLId] = GREEN;
      
      /* Pass car */
      /* Note: atomic for easier claim construction */
      carsWaiting[TLId] ? CAR;
      printf("MSC: Traffix light #%d: pass cars\n", TLId);
    };
    
    /* Forbid passing */
    atomic
    {
      printf("MSC: Traffic light #%d: RED\n", TLId);
      TLColor[TLId] = RED;
    };
    
    /* Release dependent intersections */
    if
    :: TLId == SN ->
      unlockOverlap(2);
      unlockOverlap(1);
      unlockOverlap(0);
    :: TLId == WE ->
      unlockOverlap(3);
      unlockOverlap(0);
    :: TLId == ES ->
      unlockOverlap(4);
      unlockOverlap(3);
      unlockOverlap(2);
    :: TLId == NE ->
      unlockOverlap(4);
      unlockOverlap(1);
    fi;
  od;
}

/* The main model function */
init
{
  byte TLId, OvId;
  
  /* Reset traffic lights colors */
  TLId = 0;
  do
  :: TLId < N_TRAFFIC_LIGHTS ->
    TLColor[TLId] = RED;
    TLId++;
  :: else ->
    break;
  od;
  
  atomic
  {
    /* Start intersection managers processes */
    OvId = 0;
    do
    :: OvId < N_OVERLAPS ->
      run Overlap(OvId);
      OvId++;
    :: else ->
      break;
    od;
  
    /* Start traffic lights processes */
    OvId = 0;
    do
    :: TLId < N_TRAFFIC_LIGHTS ->
      run TrafficLight(TLId);
      TLId++;
    :: else ->
      break;
    od;
  
    /* Start cars generator process */
    /*run CarsGenerator();*/
    TLId = 0;
    do
    :: TLId < N_TRAFFIC_LIGHTS ->
      run LineTrafficGenerator(TLId);
      TLId++;
    :: else ->
      break;
    od;
  }
}

/*
 * Correctness requirements.
 */

/* Car crash accident definition */
#define accident_01 (TLColor[0] == GREEN && TLColor[1] == GREEN)
#define accident_02 (TLColor[0] == GREEN && TLColor[2] == GREEN)
#define accident_03 (TLColor[0] == GREEN && TLColor[3] == GREEN)
#define accident_13 (TLColor[1] == GREEN && TLColor[3] == GREEN)
#define accident_23 (TLColor[2] == GREEN && TLColor[3] == GREEN)

/* Car waiting at traffic light definition */
#define car_waiting_0 (len(carsWaiting[0]) > 0)
#define car_waiting_1 (len(carsWaiting[1]) > 0)
#define car_waiting_2 (len(carsWaiting[2]) > 0)
#define car_waiting_3 (len(carsWaiting[3]) > 0)

/* Traffic light is green definition */
#define TL_green_0 (TLColor[0] == GREEN)
#define TL_green_1 (TLColor[1] == GREEN)
#define TL_green_2 (TLColor[2] == GREEN)
#define TL_green_3 (TLColor[3] == GREEN)
