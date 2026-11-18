import numpy as np
def proj_segmentos(P, A):
    """Para cada ponto P (n,2), segmento mais próximo do anel A (m,2): retorna (dist, idx, t)."""
    B = np.roll(A,-1,axis=0); D = B-A; L2=(D**2).sum(1)
    best=np.full(len(P),np.inf); bi=np.zeros(len(P),int); bt=np.zeros(len(P))
    for i0 in range(0,len(A),64):
        a=A[i0:i0+64]; d=D[i0:i0+64]; l2=L2[i0:i0+64]
        t=np.clip(((P[:,None,:]-a[None])*d[None]).sum(2)/l2[None],0,1)
        q=a[None]+t[...,None]*d[None]; dist=np.linalg.norm(P[:,None,:]-q,axis=2)
        j=dist.argmin(1); dm=dist[np.arange(len(P)),j]; upd=dm<best
        best[upd]=dm[upd]; bi[upd]=i0+j[upd]; bt[upd]=t[np.arange(len(P)),j][upd]
    return best,bi,bt
def deslocar(V, plano, dorso):
    """V: vértices (n,3) do cuff da grade (mesmo DW/DH, sem dorso). plano/dorso: dicts de contornos correspondentes."""
    P=V[:,:2]; melhor=np.full(len(P),np.inf); desl=np.zeros_like(P)
    for k in plano:
        A=plano[k]; Dk=dorso[k]-A
        dist,i,t=proj_segmentos(P,A); j=(i+1)%len(A)
        d=(1-t)[:,None]*Dk[i]+t[:,None]*Dk[j]
        u=dist<melhor; melhor[u]=dist[u]; desl[u]=d[u]
    W=V.copy(); W[:,:2]+=desl; return W, melhor
