"""v4b (14/11/2026): --dorso JSON (o mesmo de construir_r08a_custom.py) desfaz o deslocamento dorsal pessoal antes das regras de pintura
  (y_T4 = y - raise(x)*smooth(y,2,9)), para o batente central acompanhar a mola abaixada.
v4 sob medida (14/11/2026, Claude): --espelhado para pulseira de mao esquerda gerada com construir_r08a_custom.py --esquerda:
  as regras de pintura de costura (definidas na pulseira direita) sao avaliadas com x espelhado (x -> -x).
v3 (11/11): --dw/--dh = tamanho da pulseira R08A (gerador construir_r08a_tam.py): a pintura de costura usa as regras do T4 nas coordenadas
  do T4 (centroides levados de volta pela inversa da deformacao). v2 (11/11): renomeia o objeto do primeiro <object id=N> (antes so id 2). Troca a malha do objeto 1 de um 3MF de projeto do Bambu Studio (salvo pela GUI, com maquina/perfis/modificadores validos) por um STL novo.
Uso:  python trocar_malha_3mf.py <modelo.3mf> <novo.stl> <saida.3mf> [--costura-pulseira] [--centralizar]
  --costura-pulseira: reaplica a pintura de costura da FreshCuff R08A T4 (mesmas regras de preparar_r02.py com --pintar-bocas, coordenadas CAD).
  --centralizar: a malha nova fica centrada no objeto (pecas de outro tamanho); sem isso usa o mesmo deslocamento do modelo (mesmo referencial CAD).
Nunca sobrescreve (zip em modo 'x'). Mantem os outros objetos (modificadores), configuracoes e placa.
"""
import sys, re, zipfile, hashlib, argparse
import numpy as np, trimesh
ap=argparse.ArgumentParser(); ap.add_argument('modelo'); ap.add_argument('stl'); ap.add_argument('saida')
ap.add_argument('--costura-pulseira',action='store_true'); ap.add_argument('--dw',type=float,default=0.); ap.add_argument('--dh',type=float,default=0.); ap.add_argument('--centralizar',action='store_true'); ap.add_argument('--espelhado',action='store_true'); ap.add_argument('--dorso'); a=ap.parse_args()
cad=trimesh.load(a.stl); cad.merge_vertices()
z=zipfile.ZipFile(a.modelo)
ARQ='3D/Objects/object_1.model'
objs=z.read(ARQ).decode(); mont=z.read('3D/3dmodel.model').decode(); cfg=z.read('Metadata/model_settings.config').decode()
comp=re.search(r'<component p:path="/3D/Objects/object_1.model" objectid="1"[^>]*transform="([^"]+)"',mont)
tr=np.array(comp.group(1).split(),float); off=tr[9:12].copy()
if a.centralizar:
    b=cad.bounds; c=(b[0]+b[1])/2; h=b[1][2]-b[0][2]
    loc=cad.vertices-c; novo_off=np.array([0.0,0.0,h/2])
else:
    loc=cad.vertices-off; novo_off=off
V=cad.vertices; F=cad.faces
tags=None
if a.costura_pulseira:
    tri=V[F]; x,y,_=tri.mean(axis=1).T
    sx=-1. if a.espelhado else 1.
    x=sx*x
    import json as _j
    _sm=lambda u,lo,hi: (lambda t: t*t*(3-2*t))(np.clip((u-lo)/(hi-lo),0,1))
    if a.dorso:
        _d=_j.load(open(a.dorso)); _xr,_rr=np.array(_d['x_T4']),np.array(_d['raise'])
        undo=lambda xx,yy: yy-np.interp(xx,_xr,_rr)*_sm(yy,2.,9.)
    else:
        undo=lambda xx,yy: yy
    y=undo(x,y)
    if a.dw or a.dh:
        sm=lambda u,lo,hi: (lambda t: t*t*(3-2*t))(np.clip((u-lo)/(hi-lo),0,1))
        def fwd(x0,y0):
            w=sm(y0,-10.,0.); g=(1-w)*sm(np.abs(x0),24.,38.)+w*sm(np.abs(x0),10.,40.)
            return x0+np.sign(x0)*a.dw*g, y0+a.dh*sm(y0,-9.,7.)
        x0,y0=x.copy(),y.copy()
        for _ in range(60):
            fx,fy=fwd(x0,y0); x0-=0.7*(fx-x); y0-=0.7*(fy-y)
        fx,fy=fwd(x0,y0); print('inversa: residuo max',float(max(np.abs(fx-x).max(),np.abs(fy-y).max())))
        x,y=x0,y0
    nrm=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]); nrm/=np.linalg.norm(nrm,axis=1)[:,None]  # so a componente y das normais e usada (nao muda no espelho)
    ext=(x>48.0)&(x<52.)&(y>-6.5)&(y<-3.5)
    palma=(x>-30)&(x<-24)&(y>-19.65)&(y<-16.3)&(nrm[:,1]>.08)
    batente=(abs(x)<5.5)&(y>19.15)&(y<20.55)&(nrm[:,1]<-.08)
    paint=np.where(ext|palma|batente,'4','8').astype(object)
    if a.dw or a.dh:
        vx,vy=sx*V[:,0].copy(),V[:,1].copy(); X0,Y0=vx.copy(),vy.copy()
        for _ in range(60):
            fx,fy=fwd(X0,Y0); X0-=0.7*(fx-vx); Y0-=0.7*(fy-vy)
        V0=np.c_[X0,Y0,V[:,2]]; tri0=V0[F]; menor=tri0.min(axis=1); maior=tri0.max(axis=1)
    else:
        V0=np.c_[sx*V[:,0],undo(sx*V[:,0],V[:,1]),V[:,2]]; tri0=V0[F]; menor=tri0.min(axis=1); maior=tri0.max(axis=1)
    toca=lambda x0,x1,y0,y1: (maior[:,0]>=x0)&(menor[:,0]<=x1)&(maior[:,1]>=y0)&(menor[:,1]<=y1)
    viz=toca(46.8,53.2,-8.,-2.)|toca(-32.,-22.,-21.,-15.)|toca(-7.,7.,18.5,21.6)
    paint[viz]=''; paint[ext|palma|batente]='4'; tags=paint
    print('pintura: preferida',int((paint=='4').sum()),'bloqueada',int((paint=='8').sum()),'livre',int((paint=='').sum()))
vx=''.join('<vertex x="%.6f" y="%.6f" z="%.6f"/>'%tuple(v) for v in loc)
tx=''.join(('<triangle v1="%d" v2="%d" v3="%d"'%tuple(f))+((' paint_seam="%s"'%tags[i]) if tags is not None and tags[i] else '')+'/>' for i,f in enumerate(F))
old=re.search(r'<object id="1"[^>]*>.*?</object>',objs,re.S).group()
head=re.match(r'<object id="1"[^>]*>',old).group()
objs=objs.replace(old,head+'<mesh><vertices>'+vx+'</vertices><triangles>'+tx+'</triangles></mesh></object>',1)
nt=' '.join(comp.group(1).split()[:9]+['%.8g'%v for v in novo_off])
mont=mont.replace(comp.group(0),comp.group(0).replace(comp.group(1),nt),1)
if a.centralizar:
    mont=re.sub(r'(<item objectid="2"[^>]*transform=")([^"]+)(")',lambda m: m.group(1)+' '.join(m.group(2).split()[:9]+['128','128','0'])+m.group(3),mont,1)
nome=a.stl.replace('\\','/').split('/')[-1]
p1=re.search(r'<part id="1" subtype="normal_part".*?</part>',cfg,re.S).group()
p1n=re.sub(r'(<metadata key="(?:name|source_file)" value=")[^"]*(")',lambda m:m.group(1)+nome+m.group(2),p1)
p1n=re.sub(r'<mesh_stat face_count="\d+"',f'<mesh_stat face_count="{len(F)}"',p1n)
mx=re.search(r'<metadata key="matrix" value="([^"]+)"',p1n).group(1).split(); mx[3],mx[7],mx[11]=('%.8g'%novo_off[0],'%.8g'%novo_off[1],'%.8g'%novo_off[2])
p1n=re.sub(r'<metadata key="matrix" value="[^"]+"',f'<metadata key="matrix" value="{" ".join(mx)}"',p1n,1)
for k,i in (('x',0),('y',1),('z',2)): p1n=re.sub(rf'(<metadata key="source_offset_{k}" value=")[^"]*(")',lambda m:m.group(1)+'%.8g'%novo_off[i]+m.group(2),p1n)
cfg=cfg.replace(p1,p1n,1)
cfg=re.sub(r'(<object id="\d+">\s*<metadata key="name" value=")[^"]*(")',lambda m:m.group(1)+nome+m.group(2),cfg,1)
subs={ARQ:objs,'3D/3dmodel.model':mont,'Metadata/model_settings.config':cfg}
with zipfile.ZipFile(a.saida,'x',zipfile.ZIP_DEFLATED) as out:
    for info in z.infolist():
        out.writestr(info, subs[info.filename].encode() if info.filename in subs else z.read(info))
print('ok',a.saida,'faces',len(F),'deslocamento',novo_off.round(4).tolist(),'sha256 stl',hashlib.sha256(open(a.stl,'rb').read()).hexdigest()[:16])
