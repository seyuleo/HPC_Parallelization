# -*- coding: utf-8 -*-
"""
Created on Sat Sep  8 00:12:12 2018
Value Function Iteration

@author: Don Koh
"""


import json
from pprint import pprint
import numpy as np
import time
from scipy.stats import norm
from scipy.optimize import fminbound
from multiprocessing import Pool
from functools import partial
 

#--------------------------------#
#       HOUSEHOLD CLASS
#--------------------------------#
class Household:
    # INITIALIZATION OF THE CLASS WITH GIVEN PARAMETERS VALUES
    def __init__(self,  T           = 10,
                        na          = 1000,
                        amin        = 0.0,
                        amax        = 10.0,
                        ne          = 15,
                        ssigma_eps  = 0.02058,
                        rho_eps     = 0.99,
                        m           = 1.5,
                        ssigma      = 2,
                        bbeta       = 0.97,
                        r           = 0.07,
                        w           = 5):

        # LIFE TIME
        self.T              = T
        
        # GRID FOR a
        self.na             = na
        self.amin           = amin
        self.amax           = amax
        self.agrid          = np.zeros(self.na)

        # GRID FOR e AND TRANSITION MATRIX: PARAMETERS FOR TAUCHEN
        self.ne             = ne
        self.ssigma_eps     = ssigma_eps
        self.rho_eps        = rho_eps
        self.m              = m
        self.egrid          = np.zeros(self.ne)
        self.P              = np.zeros((self.ne, self.ne))

        # PARAMETERS FOR UTILITY FUNCTION
        self.ssigma         = ssigma
        self.bbeta          = bbeta

        # PRICES FOR PRICE TAKERS
        self.r              = r
        self.w              = w

        # INITIALIZE VALUE FUNCTION AND POLICY FUNCTIONS
        self.V              = np.zeros((T, na, ne))
        self.c0             = np.zeros((T, na, ne))
        self.a1             = np.zeros((T, na, ne))


    def get_agrid(self):
        '''
        This function constructs and returns the grid for state a.
        The grid points are in equidistance.
        '''
        astep = (self.amax - self.amin) /(self.na - 1)
        it = 0
        for i in range(self.na):
            self.agrid[i] = self.amin + it*astep
            it = it+1        
        return self.agrid

    def get_egrid(self):
        '''
        This function constructs and returns the grid for state e
        and its transition matrix P using Tauchen (1986)
        '''
        ssigma_y = np.sqrt(self.ssigma_eps**2 / (1 - self.rho_eps**2))
        estep = 2*ssigma_y*self.m / (self.ne-1)
        it = 0
        for i in range(self.ne):
            self.egrid[i] = (-self.m*np.sqrt(self.ssigma_eps**2 / (1 - self.rho_eps**2)) + it*estep)
            it = it+1
        mm = self.egrid[1] - self.egrid[0]
        for j in range(self.ne):
            for k in range(self.ne):
                if (k == 0):
                    self.P[j, k] = norm.cdf((self.egrid[k] - self.rho_eps*self.egrid[j] + (mm/2))/self.ssigma_eps)
                elif (k == self.ne-1):
                    self.P[j, k] = 1 - norm.cdf((self.egrid[k] - self.rho_eps*self.egrid[j] - (mm/2))/self.ssigma_eps)
                else:
                    self.P[j, k] = norm.cdf((self.egrid[k] - self.rho_eps*self.egrid[j] + (mm/2))/self.ssigma_eps) - \
                                   norm.cdf((self.egrid[k] - self.rho_eps*self.egrid[j] - (mm/2))/self.ssigma_eps)

        # EXPONENTIAL OF THE GRID
        for i in range(self.ne):
            self.egrid[i] = np.exp(self.egrid[i])

        return self.egrid

    def util(self,cons):
        '''
        This function returns the value of CRRA utility with ssigma
        u(c) = c**(1-ssigma)/(1-ssigma)
        '''
        if self.ssigma != 1:
            uu = cons**(1-self.ssigma)/(1-self.ssigma)
        else:
            uu = np.log(cons)
        
        return uu
    
    def set_c0(self,age,ia,ie,cons):
        '''
        This function updates the value of consumption
        '''
        self.c0[age,ia,ie]   = cons
    
    def set_a1(self,age,ia,ie,ap):
        '''
        This function updates the value of saving
        '''
        self.a1[age,ia,ie]   = ap

    def set_V0(self,age,ia,ie,VV):
        '''
        This function updates the value function
        '''
        self.V[age,ia,ie]   = VV


def bellman(ap,a0,e0,ne,agrid,V1,P1,r,w,ssigma,bbeta):
    '''
    This function computes bellman equation for a given state (a0,e0).
    Input:
        ap: evaluating point
        hh: household object
        (a0,e0) state
        V1: value function at age t+1 evaluated at (a',e')
        P1: probability distribution of e' conditional on the current e0
    Output:
        -vv: bellman equation
    ''' 
    # Initialize an expected continuation value
    EVa1    = 0
    
    # Compute expected continuation value for each e'
    for iep in range(ne):
        
        # Transition probability conditional on current e0, 
        eprob       = P1[iep]
        
        # Interpolate next period's value function evaluated at (a',e')
        # using 1-dimensional interpolation function in numpy
        V1a         = np.interp(ap,agrid,V1[:,iep])
        
        # Interpolated value cannot be NaN or Inf
        if np.isnan(V1a) or np.isinf(V1a): print("bellman: V1a is NaN.")
        
        # Compute expected value
        EVa1        += eprob*V1a

    # Compute consumption at a given (a0,e0) and a'       
    cons = (1 + r)*a0 + w*e0 - ap
    
    # Consumption must be non-negative
    if cons<=0:
        vv = -1e10
    else:
        # Compute value function
        vv  = cons**(1-ssigma)/(1-ssigma) + bbeta*EVa1
    
    return -vv



def vfi_opt(age,ne,agrid,egrid,amin,amax,V1,P,r,w,ssigma,bbeta,ind):
    '''
    This function returns value function for a given state (a0,e0) and age
    Input:
        hh: household object
        ind: a unique state that corresponds to a pair of state (a0,e0)
        age: age
    ''' 
    # Index of current state (a0,e0)
    ia = ind // ne
    ie = ind % ne
    
    # Current state (a0,e0)
    a0 = agrid[ia]
    e0 = egrid[ie]
    
    P1 = P[ie,:]

    # At each state (a0,e0), bounded minimization of a function w.r.t. a' over [amin,amax]
    # using fminbound function in scipy.
    aa = fminbound(bellman,amin,amax,args=(a0,e0,ne,agrid,V1,P1,r,w,ssigma,bbeta))
    VV = -bellman(aa,a0,e0,ne,agrid,V1,P1,r,w,ssigma,bbeta)
#    aa = fminbound(bellman,hh.amin,hh.amax,args=(hh,a0,e0,V1,P1))
#    VV = -bellman(aa,hh,a0,e0,V1,P1)
    #### full_output option takes longer than recalculating value function
#    aa, VV, err, n_func = fminbound(bellman,hh.amin,hh.amax,args=(hh,a0,e0,hh.V[age+1,:,:],hh.P[ie,:]),full_output=True)
    cc = (1 + r)*a0 + w*e0 - aa

    return VV,cc,aa


#@profile
def run_vfi_opt(num_cores):
    '''
    This function runs the main process.
    ''' 
    
    s0          = time.time()
    f0_sum      = 0
    
    #------------------------------------------#
    #      STEP1: INITIALIZATION
    #------------------------------------------#
#    print("INITIALIZATION: ")
    # NUMBER OF CORES TO BE USED
    # num_cores = 0 --> SERIAL PROCESS
    # num_cores > 0 --> PARALLEL PROCESS
#    num_cores   = 8
#    print("   Number of Cores = ", num_cores)
#    print(" ")
    
    # INITILIZE THE HOUSEHOLD CLASS
#    s1a         = time.time()
    hh          = Household()

#    f1a         = time.time() - s1a
#    run_time.append(f1a)
    
    # GRID CONSTRUCTION FOR a
#    s1b         = time.time()
    agrid       = hh.get_agrid()
#    f1b         = time.time() - s1b
#    run_time.append(f1b)
    
    # GRID CONSTRUCTION FOR e
#    s1c         = time.time()
    egrid       = hh.get_egrid()
#    f1c         = time.time() - s1c
#    run_time.append(f1c)
#    f0_sum      = f1a + f1b + f1c
    
    
    #------------------------------------------#
    #     STEP2: LIFECYCLE COMPUTATION
    #------------------------------------------#
#    print("LIFECYCLE COMPUTATION: ")
#    print(" ")
    try:
        run_time    = np.zeros(hh.T)    
        pool = Pool(processes=num_cores)
        for age in reversed(range(hh.T)):
            s2  = time.time()
        
            # EMPTY BIN FOR VALUE FUNCTION AND POLICY FUNCITONS
            results = np.zeros((hh.na*hh.ne,3))
            
            # NO GRID SEARCH AT AGE T
            if(age == hh.T-1):
                for ind in range(hh.na*hh.ne):
                    ia = ind // hh.ne
                    ie = ind % hh.ne
                    cc              = (1 + hh.r)*agrid[ia] + hh.w*egrid[ie]
                    if cc<=0: cc = 1e-5
                    results[ind][0] = hh.util(cc)   # VALUE FUNCTION
                    results[ind][1] = cc            # CONSUMPTION
                    results[ind][2] = 0.0           # SAVING
        
            # GRID SEARCH AT AGE < T
            else:
                # Parallel grid search
                vfi_opt_partial = partial(vfi_opt, age,hh.ne,hh.agrid,hh.egrid,hh.amin,hh.amax,hh.V[age+1,:,:],hh.P,hh.r,hh.w,hh.ssigma,hh.bbeta)
                results = pool.map(vfi_opt_partial, np.arange(hh.na*hh.ne))
        
                # UPDATE VALUE FUNCTION AND POLICY FUNCTIONS
            for ind in range(hh.na*hh.ne):
                ia = ind // hh.ne
                ie = ind % hh.ne
                hh.set_V0(age,ia,ie,results[ind][0])
                hh.set_c0(age,ia,ie,results[ind][1])
                hh.set_a1(age,ia,ie,results[ind][2])
        
        
            f2 = time.time() - s2
            run_time[age] = f2
            f0_sum  += f2
    #        print( "Age: ", age+1, ". Time: ", round(f2, 4), " seconds.\n")

    finally:
        pool.close()
        pool.join()
        
    # TOTAL RUNTIME
    f0 = time.time() - s0
    run_time = np.insert(run_time, 0, [f0, f0_sum])
#    print ("TOTAL ELAPSED TIME: ", round(f0_sum, 4), " seconds. \n")

    return run_time


if __name__ == "__main__":
    # Number of cores
    list_cores      = np.arange(1,33,1)
#    list_cores      = np.arange(1,9,1)
    num_list_cores  = len(list_cores)
    
    
    # Run time memory
    T        = 10;
    
    nrun        = 21
    
    # Iterate on the number of cores
    # Store the results as JSON data
    data = []
    for num_cores in list_cores:
        for num_runs in range(nrun):
        
            results = run_vfi_opt(num_cores)
        
            # Store the total run time and initialization in a JSON data
            data.append({
                    'core': int(num_cores),
                    'run': int(num_runs),
                    'age': int(-1),
                    'runtime': results[0]
            })
            data.append({
                    'core': int(num_cores),
                    'run': int(num_runs),
                    'age': int(0),
                    'runtime': results[1]
            })
            
            # Print out to a console window
            print("####### ", num_runs+1, " times run with ",num_cores, " cores #######\n")
            print ("Total Elapsed Time: ", round(results[0], 4), " seconds.")
        
            for age in range(T):
                data.append({
                        'core': int(num_cores),
                        'run': int(num_runs),
                        'age': int(age+1),
                        'runtime': results[age+2]
                })
                print( "Age: ", age+1, ". Time: ", round(results[age+2], 4), " seconds.")
        
            print(" ")    
    
        
    # Write the data to a output file
    with open("runtime_vfi_by_cores_pop_1_32.txt","w+") as outfile:
        json.dump(data, outfile)
    
    
    # Retrieve the results from the output file
    with open("runtime_vfi_by_cores_pop_1_32.txt") as json_data:
        d = json.load(json_data)
        pprint(d)
    for ik in range(len(d)):
        print(d[ik]['core'],d[ik]['run'],d[ik]['age'],d[ik]['runtime'])
